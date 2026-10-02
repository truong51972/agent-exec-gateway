# Agent Exec Gateway

A minimal control plane for giving AI agents audited, policy-controlled command execution on local or SSH-connected hosts.

The initial implementation is intentionally small: one Python process, one SQLite database, one FastAPI application serving both REST/dashboard routes and an MCP Streamable HTTP endpoint.
