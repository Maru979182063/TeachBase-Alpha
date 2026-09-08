package com.teachbase.server.ingestion.application;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.teachbase.server.identity.api.WorkspaceDirectory;
import com.teachbase.server.ingestion.infrastructure.DeliveryFiles;
import com.teachbase.server.ingestion.infrastructure.DeliveryRepository;
import com.teachbase.server.question.api.*;
import com.teachbase.server.review.api.OpenReviewCaseRequest;
import com.teachbase.server.review.api.ReviewWorkflow;
import com.teachbase.server.source.api.*;
import com.teachbase.server.taxonomy.api.TaxonomyCatalog;
import com.teachbase.server.taxonomy.api.ResolveTaxonomyNodeRequest;
import java.time.Instant;
import java.util.*;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 中文维护说明：G2 只同步接收待审核候选，成功业务行和 receipt 同事务提交；不运行模型或后台 worker。 */
@Service
public class DeliveryService {
    private final DeliveryContract contract; private final DeliveryFiles files; private final DeliveryRepository repo;
    private final WorkspaceDirectory workspaces; private final QuestionBatchImporter questions; private final QuestionRevisionDirectory revisions;
    private final QuestionIngestionLinker links; private final SourceCatalog sources; private final ReviewWorkflow reviews; private final TaxonomyCatalog taxonomy;
    private final ObjectMapper mapper;
    public record Outcome(JsonNode receipt, boolean replay) {}
    public DeliveryService(DeliveryContract contract, DeliveryFiles files, DeliveryRepository repo, WorkspaceDirectory workspaces,
            QuestionBatchImporter questions, QuestionRevisionDirectory revisions, QuestionIngestionLinker links,
            SourceCatalog sources, ReviewWorkflow reviews, TaxonomyCatalog taxonomy, ObjectMapper mapper) {
        this.contract=contract; this.files=files; this.repo=repo; this.workspaces=workspaces; this.questions=questions; this.revisions=revisions;
        this.links=links; this.sources=sources; this.reviews=reviews; this.taxonomy=taxonomy; this.mapper=mapper;
    }
    private void actor(UUID workspace, UUID actor) {
        if (actor == null || !workspaces.exists(workspace) || !workspaces.isActiveMember(workspace, actor)) throw new DeliveryException(403, "delivery_actor_not_member");
    }
    private UUID workspace(JsonNode m) {
        try { return UUID.fromString(m.path("workspaceId").asText()); } catch (Exception e) { throw new DeliveryException(400, "workspace_id_invalid"); }
    }
    @Transactional(readOnly=true)
    public JsonNode preflight(JsonNode m, UUID actor) { actor(workspace(m), actor); return inspect(m, actor); }
    private ObjectNode inspect(JsonNode m, UUID actor) {
        var issues = new ArrayList<>(contract.validate(m)); var warnings = new ArrayList<DeliveryContract.Issue>();
        if (issues.isEmpty()) {
            rejectNul(m,"",issues);
            issues.addAll(files.inspect(m));
            for (int i=0; i<m.path("questions").size(); i++) {
                var q=m.path("questions").get(i); var c=q.path("content"); var labels=q.path("classificationSuggestions"); String p="/questions/"+i;
                // 旧规范域要求明确学科和题型；不填造默认值。缺失会在预检中明确拒收。
                for (String key : List.of("subject","questionType")) if (labels.path(key).asText("").isBlank() || labels.path(key).asText("").length()>80) issues.add(new DeliveryContract.Issue("canonical_"+key+"_required_or_too_long",p+"/classificationSuggestions/"+key));
                for (String key : List.of("stage","grade")) if (labels.path(key).asText("").length()>80) issues.add(new DeliveryContract.Issue("canonical_field_too_long",p+"/classificationSuggestions/"+key));
                if (c.path("stemMarkdown").asText().isBlank() || c.path("titleMarkdown").asText().length()>512) issues.add(new DeliveryContract.Issue("canonical_content_invalid",p+"/content"));
                for(String field:List.of("materialMarkdown","stemMarkdown","answerMarkdown","analysisMarkdown")) if(c.path(field).asText().indexOf('\0')>=0) issues.add(new DeliveryContract.Issue("canonical_nul_invalid",p+"/content/"+field));
                if (labels.path("tags").isEmpty()) warnings.add(new DeliveryContract.Issue("knowledge_tags_missing",p));
                if (q.path("sourceEvidence").path("pageNumbers").isEmpty()) warnings.add(new DeliveryContract.Issue("source_pages_missing",p));
                if (labels.path("difficultyStars").isNull()) warnings.add(new DeliveryContract.Issue("difficulty_missing",p));
                for (var tag:labels.path("tags")) try { taxonomy.resolve(new ResolveTaxonomyNodeRequest(workspace(m),actor,UUID.fromString(tag.path("taxonomyVersionId").asText()),tag.path("nodeKey").asText())); }
                    catch (RuntimeException e) { issues.add(new DeliveryContract.Issue("taxonomy_suggestion_unresolved",p+"/classificationSuggestions/tags")); }
                Set<String> keys=new HashSet<>(); for(var a:c.path("media")) keys.add(a.path("assetKey").asText());
                // 仅对显式资产 URI 作结构引用验证，不用正则决定题义或标签。
                var matcher=Pattern.compile("asset://([^\\s)\"'<>]+)").matcher(c.toString().replace("\\\"","\""));
                while(matcher.find()) if(!keys.contains(matcher.group(1))) issues.add(new DeliveryContract.Issue("markdown_asset_unresolved",p+"/content"));
            }
            String old=repo.packageDigest(workspace(m),UUID.fromString(m.path("packageId").asText()));
            if(old!=null&&!old.equals(contract.requestDigest(m))) issues.add(new DeliveryContract.Issue("delivery_package_conflict","/packageId"));
            var prior=repo.receipt(workspace(m),UUID.fromString(m.path("importRequestId").asText()));
            if(prior!=null&&!prior.path("deliveryDigest").asText().equals(contract.requestDigest(m))) issues.add(new DeliveryContract.Issue("delivery_request_conflict","/importRequestId"));
        }
        var result=mapper.createObjectNode(); result.put("preflightSchemaVersion",1); result.put("eligible",issues.isEmpty()); result.put("checkedAt",Instant.now().toString());
        try { result.put("deliveryDigest",m.isObject()?contract.requestDigest(m):null); } catch(DeliveryException e) { result.putNull("deliveryDigest"); }
        result.set("issues",mapper.valueToTree(issues)); result.set("warnings",mapper.valueToTree(warnings)); result.put("databaseWritten",false); return result;
    }
    @Transactional(timeout=120)
    public Outcome commit(JsonNode m, UUID actor) {
        UUID workspace=workspace(m); actor(workspace,actor);
        if(!contract.validate(m).isEmpty()) throw new DeliveryException(422,"delivery_contract_invalid");
        UUID request=UUID.fromString(m.path("importRequestId").asText()), pack=UUID.fromString(m.path("packageId").asText()); String digest=contract.requestDigest(m);
        repo.lock(workspace,request,pack);
        actor(workspace,actor);
        var prior=repo.receipt(workspace,request);
        if(prior!=null) { if(!prior.path("deliveryDigest").asText().equals(digest)) throw new DeliveryException(409,"delivery_request_conflict"); return new Outcome(prior,true); }
        String old=repo.packageDigest(workspace,pack); if(old!=null&&!old.equals(digest)) throw new DeliveryException(409,"delivery_package_conflict");
        var check=inspect(m,actor); if(!check.path("eligible").asBoolean()) throw new DeliveryException(422,"delivery_preflight_failed_at_commit");
        repo.begin(m,actor,digest);
        // 同一个不可变包的新请求复用已提交业务映射；即使题目已审核也不重开审核任务。
        if(old!=null) {
            ObjectNode receipt=repo.packageReceipt(workspace,pack).deepCopy(); receipt.put("importRequestId",request.toString()); receipt.put("completedAt",Instant.now().toString());
            for(var item:receipt.path("items")) repo.item(workspace,request,item);
            repo.complete(workspace,request,receipt); return new Outcome(receipt,false);
        }
        Map<String,DeliveryFiles.Registered> registered=new LinkedHashMap<>(); Map<String,JsonNode> fileEntries=new HashMap<>();
        Set<String> referencedKeys=new HashSet<>(), referencedHashes=new HashSet<>();
        for(var d:m.path("sourceDocuments")) referencedKeys.add(d.path("fileKey").asText());
        for(var q:m.path("questions")) { for(var k:q.path("sourceEvidence").path("evidenceFileKeys")) referencedKeys.add(k.asText()); for(var a:q.path("content").path("media")) referencedHashes.add(a.path("sha256").asText()); }
        for(var f:m.path("files")) {
            String key=f.path("fileKey").asText(); var file=files.store(m,f,actor); registered.put(key,file); fileEntries.put(key,f);
            repo.file(workspace,pack,key,file,referencedKeys.contains(key)||referencedHashes.contains(file.sha256()));
        }
        Map<String,UUID> documentIds=new HashMap<>();
        for(var d:m.path("sourceDocuments")) {
            var f=registered.get(d.path("fileKey").asText());
            var id=sources.registerDocument(new RegisterSourceDocumentCommand(workspace,actor,f.fileVersionId(),"delivery-file/"+f.sha256(),"structured_import","","","","",d));
            documentIds.put(d.path("documentKey").asText(),id.id());
        }
        var items=mapper.createArrayNode();
        for(var q:m.path("questions")) {
            var c=q.path("content"); var labels=q.path("classificationSuggestions"); String key=contract.sourceKey(m,q);
            var domainContent=mapper.createObjectNode(); domainContent.put("schemaVersion",1); domainContent.set("deliveryContent",c);
            var sub=domainContent.putArray("subquestions"); for(var s:c.path("subquestions")) sub.addObject().put("markdown",s.asText()); domainContent.put("teaching_note_md",c.path("teachingNoteMarkdown").asText());
            var provenance=mapper.createObjectNode(); provenance.put("deliverySchemaVersion",1); provenance.put("packageId",pack.toString()); provenance.put("importRequestId",request.toString());
            provenance.put("sourceSystem",m.path("sourceSystem").asText()); provenance.put("identityMode","one_shot_candidate"); provenance.set("identity",q.path("identity"));
            provenance.set("pipeline",m.path("pipeline")); provenance.set("classificationSuggestions",labels); provenance.set("sourceEvidence",q.path("sourceEvidence")); provenance.put("deliveryContentHash",contract.contentHash(q));
            var assets=provenance.putObject("assetFiles"); for(var a:c.path("media")) assets.putObject(a.path("assetKey").asText()).put("sha256",a.path("sha256").asText());
            var input=new QuestionImportItem("delivery-"+key.substring(key.lastIndexOf('/')+1),"candidate_delivery_v1",key,"pending_review",
                labels.path("subject").asText(),labels.path("stage").asText(""),labels.path("grade").asText(""),labels.path("questionType").asText(),c.path("titleMarkdown").asText(),"","",mapper.createArrayNode(),
                labels.path("difficultyStars").isNull()?null:labels.path("difficultyStars").asInt(),c.path("materialMarkdown").asText(),c.path("stemMarkdown").asText(),c.path("options"),c.path("answerMarkdown").asText(),c.path("analysisMarkdown").asText(),domainContent,provenance,null,null,null);
            var imported=questions.importBatch(new BulkQuestionImportRequest(workspace,actor,List.of(input))).results().getFirst();
            UUID doc=documentIds.get(q.path("sourceDocumentKey").asText());
            var pages=q.path("sourceEvidence").path("pageNumbers"); Integer page=pages.isEmpty()?null:pages.get(0).asInt();
            var region=sources.registerRegion(new RegisterSourceRegionCommand(workspace,actor,doc,imported.questionRevisionId().toString(),"question",page,null,null,input.stemMarkdown(),q.path("sourceEvidence")));
            links.linkSource(new QuestionSourceEvidenceCommand(workspace,imported.questionId(),imported.questionRevisionId(),doc,region.id(),"",page,page,q.path("sourceEvidence")));
            var review=reviews.open(new OpenReviewCaseRequest(workspace,actor,imported.questionRevisionId(),null));
            var item=items.addObject(); item.put("itemKey",q.path("itemKey").asText()); item.put("questionId",imported.questionId().toString()); item.put("questionRevisionId",imported.questionRevisionId().toString()); item.put("reviewCaseId",review.reviewCaseId().toString()); item.put("sourceRegionId",region.id().toString());
            item.put("contentHash",contract.contentHash(q)); item.put("domainContentHash",revisions.findAll(workspace,List.of(imported.questionRevisionId())).getFirst().contentHash());
            repo.item(workspace,request,item);
        }
        // 成功回执前再次核验受控存储；预检通过从不替代提交时的状态/字节检查。
        if(!files.inspect(m).isEmpty()) throw new DeliveryException(422,"delivery_files_changed_before_commit");
        var receipt=mapper.createObjectNode(); receipt.put("receiptSchemaVersion",1); receipt.put("workspaceId",workspace.toString()); receipt.put("importRequestId",request.toString()); receipt.put("packageId",pack.toString()); receipt.put("deliveryDigest",digest); receipt.put("status","succeeded"); receipt.put("completedAt",Instant.now().toString()); receipt.set("items",items); receipt.set("warnings",check.path("warnings"));
        repo.complete(workspace,request,receipt); return new Outcome(receipt,false);
    }
    @Transactional(readOnly=true)
    public JsonNode receipt(UUID workspace,UUID request,UUID actor) { actor(workspace,actor); var r=repo.receipt(workspace,request); if(r==null) throw new DeliveryException(404,"delivery_request_not_found_or_uncommitted"); return r; }
    private void rejectNul(JsonNode node,String pointer,List<DeliveryContract.Issue> issues) {
        if(node.isTextual()&&node.asText().indexOf('\0')>=0) issues.add(new DeliveryContract.Issue("postgres_json_nul_unsupported",pointer));
        if(node.isObject()) node.fields().forEachRemaining(e->{
            if(e.getKey().indexOf('\0')>=0) issues.add(new DeliveryContract.Issue("postgres_json_nul_unsupported",pointer));
            rejectNul(e.getValue(),pointer+"/"+e.getKey(),issues);
        });
        else if(node.isArray()) for(int i=0;i<node.size();i++) rejectNul(node.get(i),pointer+"/"+i,issues);
    }
}
