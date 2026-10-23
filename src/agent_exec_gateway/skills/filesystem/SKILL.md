# Filesystem

File transfer reuses the gateway's normal execution, policy, approval, and audit path.

- Read text: `argv=["@file.read", "/path/to/file"]`
- List directory: `argv=["@file.list", "/path/to/directory"]`
- Write text: `argv=["@file.write", "/path/to/file"]` with
  `payload={"content": "..."}`

Use `skill="filesystem"` when the client has a filesystem skill grant.

Prefer reading before writing. Do not overwrite a file unless the desired final
content is known.
