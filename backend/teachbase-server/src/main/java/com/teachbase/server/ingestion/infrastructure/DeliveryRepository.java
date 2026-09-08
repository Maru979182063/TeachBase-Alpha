package com.teachbase.server.ingestion.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.ingestion.application.DeliveryException;
import java.util.UUID;
import org.jooq.DSLContext;
import org.springframework.stereotype.Repository;

/** 中文维护说明：只拥有 delivery 表；业务表通过公开领域端口写入，SQL 约束保证回执原子完整。 */
@Repository
public class DeliveryRepository {
    private final DSLContext db; private final ObjectMapper mapper;
    public DeliveryRepository(DSLContext db, ObjectMapper mapper) { this.db = db; this.mapper = mapper; }
    public void lock(UUID workspace, UUID request, UUID pack) {
        db.fetch("select pg_advisory_xact_lock(hashtextextended(?,0))", "delivery-request:" + workspace + ":" + request);
        db.fetch("select pg_advisory_xact_lock(hashtextextended(?,0))", "delivery-package:" + workspace + ":" + pack);
    }
    public JsonNode receipt(UUID workspace, UUID request) {
        var row = db.fetchOne("select receipt_json::text as body from teachbase_app.delivery_request where workspace_id=? and import_request_id=? and status='succeeded'", workspace, request);
        try { return row == null ? null : mapper.readTree(row.get("body", String.class)); } catch (Exception e) { throw new IllegalStateException(e); }
    }
    public String packageDigest(UUID workspace, UUID pack) {
        var r = db.fetchOne("select delivery_digest from teachbase_app.delivery_package where workspace_id=? and package_id=?", workspace, pack);
        return r == null ? null : r.get("delivery_digest", String.class);
    }
    public JsonNode packageReceipt(UUID workspace, UUID pack) {
        var row = db.fetchOne("select receipt_json::text as body from teachbase_app.delivery_request where workspace_id=? and package_id=? and status='succeeded' order by received_at,import_request_id limit 1", workspace, pack);
        try { if (row == null) throw new IllegalStateException("delivery_package_receipt_missing"); return mapper.readTree(row.get("body",String.class)); }
        catch (java.io.IOException e) { throw new IllegalStateException(e); }
    }
    public void begin(JsonNode manifest, UUID actor, String digest) {
        UUID workspace = UUID.fromString(manifest.path("workspaceId").asText()), pack = UUID.fromString(manifest.path("packageId").asText()), request = UUID.fromString(manifest.path("importRequestId").asText());
        String old = packageDigest(workspace, pack);
        if (old != null && !old.equals(digest)) throw new DeliveryException(409, "delivery_package_conflict");
        db.execute("insert into teachbase_app.delivery_package(workspace_id,package_id,delivery_digest,manifest_json,created_by) values(?,?,?,?::jsonb,?) on conflict do nothing", workspace, pack, digest, manifest.toString(), actor);
        db.execute("insert into teachbase_app.delivery_request(workspace_id,import_request_id,package_id,delivery_digest,status,expected_items,received_by) values(?,?,?,?,'processing',?,?)", workspace, request, pack, digest, manifest.path("questions").size(), actor);
    }
    public void file(UUID workspace, UUID pack, String key, DeliveryFiles.Registered file, boolean used) {
        db.execute("insert into teachbase_app.delivery_package_file(workspace_id,package_id,file_key,file_version_id,sha256,is_referenced) values(?,?,?,?,?,?) on conflict do nothing", workspace, pack, key, file.fileVersionId(), file.sha256(), used);
    }
    public void item(UUID workspace, UUID request, JsonNode item) {
        db.execute("insert into teachbase_app.delivery_request_item(workspace_id,import_request_id,item_key,question_id,question_revision_id,review_case_id,source_region_id,delivery_content_hash,domain_content_hash) values(?,?,?,?,?,?,?,?,?)",
          workspace, request, item.path("itemKey").asText(), UUID.fromString(item.path("questionId").asText()), UUID.fromString(item.path("questionRevisionId").asText()),
          UUID.fromString(item.path("reviewCaseId").asText()), UUID.fromString(item.path("sourceRegionId").asText()), item.path("contentHash").asText(), item.path("domainContentHash").asText());
    }
    public void complete(UUID workspace, UUID request, JsonNode receipt) {
        db.execute("update teachbase_app.delivery_request set status='succeeded',receipt_json=?::jsonb,completed_at=clock_timestamp() where workspace_id=? and import_request_id=? and status='processing'", receipt.toString(), workspace, request);
    }
}
