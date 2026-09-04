package com.teachbase.server.exporting.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.teachbase.server.fileasset.api.StoredFileDirectory;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class RegisteredImageResolverTest {
    @TempDir Path temp;
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void resolvesRegisteredImageAndEmbedsWithoutChangingSourceAst() throws Exception {
        UUID workspace = UUID.randomUUID();
        byte[] bytes = "image bytes".getBytes();
        String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        Path source = temp.resolve("source.png"); Files.write(source, bytes);
        var resolver = new RegisteredImageResolver((w, h) -> w.equals(workspace) && h.equals(sha)
                ? Optional.of(new StoredFileDirectory.StoredFile("source.png", sha, "image/png", bytes.length)) : Optional.empty());
        var ast = json.readTree("{\"t\":\"Image\",\"c\":[[\"\",[],[]],[],[\"tbasset:" + sha + "\",\"\"]]}");
        Path work = Files.createDirectory(temp.resolve("work"));
        resolver.resolve(ast, workspace, temp, work);
        assertThat(ast.path("c").get(2).get(0).asText()).isEqualTo("assets/" + sha + ".png");
        var docx = ast.deepCopy(); resolver.embedForDocx(docx, work);
        assertThat(docx.path("c").get(2).get(0).asText()).startsWith("data:image/png;base64,");
        assertThat(ast.path("c").get(2).get(0).asText()).startsWith("assets/");
        Files.writeString(source, "tampered");
        var changed = json.readTree("{\"t\":\"Image\",\"c\":[[\"\",[],[]],[],[\"tbasset:" + sha + "\",\"\"]]}");
        assertThatThrownBy(() -> resolver.resolve(changed, workspace, temp, work)).hasMessage("render_image_bytes_mismatch");
    }

    @Test
    void refusesExternalAndUnregisteredImages() throws Exception {
        var resolver = new RegisteredImageResolver((w, h) -> Optional.empty());
        for (String uri : new String[]{"https://example.invalid/a.png", "../../a.png", "asset://docx_media_1", "tbasset:" + "a".repeat(64)}) {
            var ast = json.readTree("{\"t\":\"Image\",\"c\":[[\"\",[],[]],[],[\"" + uri + "\",\"\"]]}");
            assertThatThrownBy(() -> resolver.resolve(ast, UUID.randomUUID(), temp, temp)).hasMessage("render_image_not_registered");
        }
    }

    @Test
    void adaptsCircledNumbersOnlyInsideMathNodes() throws Exception {
        var resolver = new RegisteredImageResolver((w, h) -> Optional.empty());
        var ast = json.readTree("[{\"t\":\"Math\",\"c\":[{\"t\":\"InlineMath\"},\"\\\\textcircled{1}\"]},"
                + "{\"t\":\"Str\",\"c\":\"\\\\textcircled{1}\"}]");
        resolver.resolve(ast, UUID.randomUUID(), temp, temp);
        assertThat(ast.get(0).path("c").get(1).asText()).isEqualTo("\\text{①}");
        assertThat(ast.get(1).path("c").asText()).isEqualTo("\\textcircled{1}");
    }
}
