# Agent Exec Gateway

Agent Exec Gateway (AEG) is a small control plane for giving AI agents policy-controlled, audited command execution on the local machine or SSH-connected hosts.

The design deliberately stays small:

- one Python process
- one FastAPI application
- MCP Streamable HTTP and REST/dashboard on the same port
- one SQLite database
- local and SSH executors behind one interface
- `ALLOW` / `ASK` / `DENY` command policy
- approval and execution audit records

## Stack

- FastAPI + Uvicorn
- official MCP Python SDK
- Pydantic v2 + pydantic-settings
- SQLAlchemy 2 async + aiosqlite
- AsyncSSH
- Jinja2 dashboard
- Typer CLI

## Run

```bash
uv sync --extra dev
uv run aeg serve
```

By default AEG binds to `127.0.0.1:8000`.

- Dashboard: `http://127.0.0.1:8000/`
- REST API: `http://127.0.0.1:8000/api`
- MCP: `http://127.0.0.1:8000/mcp/`
- OpenAPI: `http://127.0.0.1:8000/docs`

The database is created at `data/aeg.db`. A `local` host is seeded automatically.

## MCP tools

The initial MCP surface is intentionally tiny:

- `exec(host, argv, cwd?)`
- `execution_status(execution_id)`
- `hosts()`

`argv` is always an array. AEG does not accept arbitrary shell command strings.

Example conceptual call:

```json
{
  "host": "local",
  "argv": ["git", "status"],
  "cwd": "/home/user/project"
}
```

## Policy

Policy defaults to `ASK`. Rules match client, host, executable and an optional argv prefix. The most specific matching rule wins.

Example rules:

| client | host | command | args prefix | decision |
| --- | --- | --- | --- | --- |
| `*` | `*` | `git` | `["status"]` | `allow` |
| `*` | `*` | `git` | `["diff"]` | `allow` |
| `*` | `*` | `git` | `["push"]` | `ask` |
| `*` | `*` | `sudo` | `[]` | `deny` |

An `ASK` execution is persisted as `awaiting_approval`. Approve or deny it from REST/dashboard, then query the execution status again.

## SSH

SSH hosts store connection metadata only. Private keys are referenced by filesystem path and are never stored in SQLite.

Remote commands are built from structured argv using POSIX quoting before being sent through SSH. Local execution uses `asyncio.create_subprocess_exec(..., shell=False)`.

For a first deployment, keep AEG private (localhost, Tailscale, or another authenticated tunnel). Authentication/client identity is intentionally deferred until the execution core is stable.

## Development

```bash
uv run ruff check .
uv run pytest
```

## Non-goals for the MVP

No Redis, Celery, Postgres, React SPA, OPA/Casbin, Kubernetes, distributed workers, or plugin framework. Those should only be added when a concrete use case requires them.
