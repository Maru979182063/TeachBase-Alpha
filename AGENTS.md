# Long-Term Working Rules

## Encoding / Mojibake Confirmation Rule

When text appears garbled in PowerShell, terminal output, logs, or tool output, do not immediately assume the source file is corrupt.

Before editing or replacing the file, verify the actual bytes and decoding explicitly, for example by reading the file as bytes and decoding it as UTF-8 in Python, or by using a reliable hex/encoding inspection command.

Separate these cases clearly:

1. Display-layer mojibake: the file bytes are valid and decode to the intended text, but the terminal rendered them incorrectly.
2. File-content mojibake: the bytes decode successfully but the decoded content is already corrupted.
3. Encoding failure: the bytes do not decode with the expected encoding.

Only change the file after confirming case 2 or case 3, or after the user explicitly asks for a rewrite. If the issue is only case 1, leave the file unchanged and report that it is a display/console encoding issue.
