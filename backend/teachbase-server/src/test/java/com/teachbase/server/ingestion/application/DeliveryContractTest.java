package com.teachbase.server.ingestion.application;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/** 中文维护说明：黄金向量由已验收 G0 Python 计算，验证 Java 编码、摘要和 schema 拒绝规则。 */
class DeliveryContractTest {
    private final ObjectMapper mapper=new ObjectMapper();
    private final DeliveryContract contract=new DeliveryContract(mapper);
    @Test void pythonGoldenVectorsMatchJava() throws Exception {
        try(var in=getClass().getResourceAsStream("/g0-contract-vectors.json")) {
            for(var v:mapper.readTree(in)) {
                var m=v.path("manifest"); assertTrue(contract.validate(m).isEmpty(),v.path("name").asText());
                assertEquals(v.path("canonical").asText(),new String(contract.canonical(m),StandardCharsets.UTF_8));
                assertEquals(v.path("deliveryDigest").asText(),contract.requestDigest(m));
                assertEquals(v.path("contentHash").asText(),contract.contentHash(m.path("questions").get(0)));
            }
        }
    }
    @Test void rejectsDuplicateJsonAndUnknownTopLevelAndFakeContentHash() throws Exception {
        assertThrows(DeliveryException.class,()->contract.parse("{\"a\":1,\"a\":2}".getBytes(StandardCharsets.UTF_8)));
        assertThrows(DeliveryException.class,()->contract.parse("{} {}".getBytes(StandardCharsets.UTF_8)));
        assertThrows(DeliveryException.class,()->contract.parse(new byte[0]));
        var vector=mapper.readTree(getClass().getResourceAsStream("/g0-contract-vectors.json")).get(0);
        ObjectNode m=vector.path("manifest").deepCopy(); m.put("deliveryDigest","0".repeat(64));
        assertFalse(contract.validate(m).isEmpty()); m.remove("deliveryDigest");
        ((ObjectNode)m.path("questions").get(0)).put("contentHash","0".repeat(64));
        assertTrue(contract.validate(m).stream().anyMatch(i->i.code().equals("content_hash_mismatch")));
    }
    @Test void distinctOneShotPackagesCannotMatchIdentity() throws Exception {
        ObjectNode m=mapper.readTree(getClass().getResourceAsStream("/g0-contract-vectors.json")).get(0).path("manifest").deepCopy();
        String before=contract.sourceKey(m,m.path("questions").get(0)); m.put("packageId","00000000-0000-4000-8000-000000000099");
        assertNotEquals(before,contract.sourceKey(m,m.path("questions").get(0)));
    }
}
