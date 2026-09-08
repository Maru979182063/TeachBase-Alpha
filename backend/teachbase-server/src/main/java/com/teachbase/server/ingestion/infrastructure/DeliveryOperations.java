package com.teachbase.server.ingestion.infrastructure;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import org.jooq.DSLContext;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** 中文维护说明：存活、接收依赖、导出配置分开报告；轻量健康探测不代替全量对账和真实导出演练。 */
@Component
public class DeliveryOperations {
    private final DSLContext db;private final Path storage;private final boolean renderEnabled;private final String pandoc,typst;
    public DeliveryOperations(DSLContext db,@Value("${teachbase.rendering.storage-root}") String storage,
            @Value("${teachbase.rendering.enabled}") boolean renderEnabled,@Value("${teachbase.rendering.pandoc-path}") String pandoc,
            @Value("${teachbase.rendering.typst-path}") String typst) {
        this.db=db;this.storage=Path.of(storage);this.renderEnabled=renderEnabled;this.pandoc=pandoc;this.typst=typst;
    }
    public Map<String,Object> health() {
        var result=new LinkedHashMap<String,Object>();boolean database=false,bytes=false;long usable=0;
        try { database=db.fetchOne("select count(*) as n from teachbase_app.delivery_request where status='processing'").get("n",Long.class)==0; }catch(RuntimeException ignored) {}
        try {bytes=Files.isDirectory(storage)&&Files.isReadable(storage)&&Files.isWritable(storage);usable=Files.getFileStore(storage).getUsableSpace();}catch(Exception ignored){}
        result.put("healthSchemaVersion",1);result.put("liveness","UP");result.put("ingestion",database&&bytes?"UP":"DOWN");
        result.put("database",database?"UP":"DOWN");result.put("storage",bytes?"READ_WRITE":"UNAVAILABLE");result.put("storageUsableBytes",usable);
        result.put("deliveryContract","candidate-delivery-v1");result.put("productionStableAuthorities",0);
        result.put("export",!renderEnabled?"DISABLED":executable(pandoc)&&executable(typst)?"TOOLS_PRESENT_UNVERIFIED":"TOOLS_MISSING");
        result.put("fullConsistencyCheck","use_delivery_storage_maintenance_audit");return result;
    }
    private boolean executable(String configured) {
        Path p=Path.of(configured);if(p.isAbsolute()||p.getNameCount()>1)return Files.isRegularFile(p)&&Files.isExecutable(p);
        for(String dir:System.getenv().getOrDefault("PATH","").split(java.io.File.pathSeparator)) {
            Path candidate=Path.of(dir,configured);if(Files.isRegularFile(candidate)&&Files.isExecutable(candidate))return true;
            if(System.getProperty("os.name").startsWith("Windows")&&Files.isRegularFile(Path.of(dir,configured+".exe")))return true;
        }
        return false;
    }
}
