# Agent Exec Gateway

Agent Exec Gateway (AEG) is a small control plane that lets AI agents execute
structured commands on local or SSH-connected machines with explicit policy,
human approval, and auditability.

It intentionally stays a **single Python process + SQLite database**:

```text
MCP / REST / Dashboard
          │
          ▼
     FastAPI app
          │
   ┌──────┼────────┐
   ▼      ▼        ▼
 Policy Approval  Audit
   │
   ▼
ExecutionService
   │
   ├── Local subprocess (shell=False)
   ├── SSH via AsyncSSH
   └── SFTP-backed file operations
```

## What is included

- FastAPI dashboard + REST + MCP Streamable HTTP on one port
- SQLite + SQLAlchemy 2 async persistence
- structured `argv` execution; no raw shell command API
- local and SSH execution
- SSH key pairing helper (generate once, install once)
- `ALLOW` / `ASK` / `DENY` command policy
- human approvals with **Allow once / Always allow / Deny**
- named clients with bearer tokens
- MCP session tracking
- append-only application audit events
- background execution with incremental output chunks
- file read/list/write over local filesystem or SFTP through the same policy path
- skill registry based on `SKILL.md` + `metadata.yaml`
- skill grants and host capability detection
- multi-host management
- Jinja dashboard with no separate frontend build

## Quick start

```bash
uv sync --extra dev
uv run aeg serve
```

Default endpoints:

```text
Dashboard    http://127.0.0.1:8000/
REST/OpenAPI http://127.0.0.1:8000/docs
MCP          http://127.0.0.1:8000/mcp/
SQLite       ./data/aeg.db
```

The built-in `local` host is created automatically.

## MCP surface

AEG deliberately keeps the MCP tool surface small:

- `exec(host, argv, cwd?, skill?, wait?, payload?)`
- `execution_status(execution_id, after_sequence?)`
- `hosts()`
- `capabilities(host, refresh?)`

Skills are exposed as MCP resources:

```text
skills://index
skills://browserskill
skills://git-read
skills://git-write
skills://docker-read
skills://python-test
skills://filesystem
gateway://help
```

Example command:

```json
{
  "host": "workstation",
  "argv": ["bsk", "snapshot", "--json"],
  "skill": "browserskill"
}
```

AEG never accepts a caller-provided raw shell string.

## Background execution and output streaming

Set `wait=false`:

```json
{
  "host": "local",
  "argv": ["uv", "run", "pytest"],
  "wait": false
}
```

The first response contains an execution id. Poll:

```text
execution_status(execution_id, after_sequence=0)
```

The response contains output chunks and a `next_sequence` cursor. Pass that cursor
on the next poll to receive only new output.

This gives long-running agent jobs incremental visibility without Redis, Celery,
or another worker process.

## SSH hosts

Register:

```bash
uv run aeg host add workstation workstation.tailnet --username truong
```

Generate/reuse a dedicated gateway key:

```bash
uv run aeg host pairing workstation
```

AEG prints the public key and a one-time command to append it to
`~/.ssh/authorized_keys` on the target.

Then verify and scan capabilities:

```bash
uv run aeg host test workstation
uv run aeg host scan workstation
```

AEG uses standard SSH host verification from `~/.ssh/known_hosts`. Connect with
normal `ssh` once (or otherwise establish the host key) before using the gateway.

Private key material is stored as a local file under `data/keys/`; it is not
stored in SQLite.

## Clients and authentication

Create a named client:

```bash
uv run aeg client create chatgpt
```

The raw bearer token is printed once. Only its SHA-256 hash and a short prefix
are persisted.

Send it as:

```text
Authorization: Bearer <token>
```

Set:

```bash
AEG_MCP_AUTH_REQUIRED=true
```

to reject unauthenticated MCP HTTP requests. The default remains `false` because
AEG binds to `127.0.0.1` by default and is convenient to dogfood locally.

Do not expose the gateway directly to the public Internet. Put it behind a
private network/tunnel and enable client authentication.

## Policy

Without a matching rule, the default decision is `ASK`.

Example command rules:

```text
client   host          command   args prefix   decision
*        *             sudo                    DENY
chatgpt  workstation   git       status        ALLOW
chatgpt  workstation   git       push          ASK
```

Rules are selected by specificity:

1. client
2. host
3. command
4. longest argument prefix

A direct command rule is authoritative over a skill grant.

## Skills

A skill is **procedure + permission metadata**, not an executable.

```text
skill
├── metadata.yaml
└── SKILL.md
```

For example BrowserSkill declares `bsk` as a required host command and teaches
the agent to snapshot before interaction.

Capability scanning checks required commands per host:

```bash
uv run aeg host scan workstation
```

A skill grant can then say:

```text
client=chatgpt
host=workstation
skill=browserskill
decision=allow
```

The grant only covers commands declared by that skill. It does not turn into
arbitrary shell access.

## File transfer

File operations reuse `exec`, policy, approval, audit, and SSH/SFTP:

```json
{"host":"workstation","argv":["@file.read","/tmp/example.txt"],"skill":"filesystem"}
```

```json
{"host":"workstation","argv":["@file.list","/tmp"],"skill":"filesystem"}
```

```json
{
  "host":"workstation",
  "argv":["@file.write","/tmp/example.txt"],
  "skill":"filesystem",
  "payload":{"content":"hello"}
}
```

Because these are normal gateway executions, they can be `ALLOW`, `ASK`, or
`DENY` and remain visible in the same audit trail.

## BrowserSkill dogfood flow

The initial real-world target is:

```text
ChatGPT / other MCP client
            │
            ▼
    Agent Exec Gateway
            │ SSH
            ▼
       workstation
            │
      bsk command
            ▼
 Tencent BrowserSkill
            │
            ▼
           Edge
```

No BrowserSkill-specific MCP server is required. AEG is only the controlled
execution transport; `SKILL.md` provides the procedure.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
```

The architecture is deliberately a modular monolith. New transports or
capabilities should plug into the execution/service boundary rather than create
new services unless a concrete scaling requirement appears.
