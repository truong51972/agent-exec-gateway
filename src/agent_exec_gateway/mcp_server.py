from mcp.server import MCPServer
from sqlalchemy import select

from .auth import ClientService, RequestIdentity, mcp_request_identity
from .db import SessionLocal
from .hosts import HostService
from .models import Host
from .schemas import ExecRequest, HostRead
from .services import ExecutionService
from .skills import CapabilityService, registry

mcp = MCPServer("Agent Exec Gateway")


async def _principal(session) -> tuple[str, str | None]:
    identity = mcp_request_identity.get() or RequestIdentity()
    return await ClientService(session).resolve(
        identity.bearer_token,
        protocol="mcp",
        external_session_id=identity.external_session_id,
    )


@mcp.tool()
async def exec(
    host: str,
    argv: list[str],
    cwd: str | None = None,
    skill: str | None = None,
    wait: bool = True,
    payload: dict | None = None,
) -> dict:
    """Execute structured argv on a managed host subject to gateway policy."""
    async with SessionLocal() as session:
        client, session_id = await _principal(session)
        result = await ExecutionService(session).submit(
            ExecRequest(
                host=host,
                argv=argv,
                cwd=cwd,
                skill=skill,
                wait=wait,
                payload=payload or {},
            ),
            client=client,
            session_id=session_id,
        )
        return result.model_dump(mode="json")


@mcp.tool()
async def execution_status(execution_id: str, after_sequence: int = 0) -> dict:
    """Return execution state plus output chunks newer than after_sequence."""
    async with SessionLocal() as session:
        await _principal(session)
        result = await ExecutionService(session).status(
            execution_id,
            after_sequence=after_sequence,
        )
        if result is None:
            return {"error": "execution not found", "execution_id": execution_id}
        return result.model_dump(mode="json")


@mcp.tool()
async def hosts() -> list[dict]:
    """List enabled execution hosts and their cached skill capabilities."""
    async with SessionLocal() as session:
        await _principal(session)
        items = (
            await session.scalars(
                select(Host).where(Host.enabled.is_(True)).order_by(Host.name)
            )
        ).all()
        response: list[dict] = []
        capabilities = CapabilityService(session)
        for item in items:
            data = HostRead.model_validate(item).model_dump(mode="json")
            data["skills"] = [
                capability.skill
                for capability in await capabilities.cached(item.name)
                if capability.available
            ]
            response.append(data)
        return response


@mcp.tool()
async def capabilities(host: str, refresh: bool = False) -> list[dict]:
    """Return skill capabilities for a host, optionally refreshing detection."""
    async with SessionLocal() as session:
        await _principal(session)
        if refresh:
            rows = await HostService(session).scan_capabilities(host)
        else:
            rows = await CapabilityService(session).cached(host)
        return [row.model_dump(mode="json") for row in rows]


@mcp.resource("skills://index")
def skills_index() -> str:
    """List available gateway skills."""
    return registry.render_index()


@mcp.resource("skills://{name}")
def skill_instructions(name: str) -> str:
    """Return instructions for one installed skill."""
    skill = registry.get(name)
    if skill is None:
        return f"# Unknown skill\n\nNo skill named `{name}` is installed."
    return skill.instructions


@mcp.resource("gateway://help")
def gateway_help() -> str:
    """Explain the compact Agent Exec Gateway execution surface."""
    return """# Agent Exec Gateway

Use `exec(host, argv, cwd?, skill?, wait?)` for commands.

The gateway never accepts a raw shell string. Pass structured argv, for example:

`["git", "status"]`

For background execution set `wait=false`, then poll `execution_status` with
the returned execution id. The status response contains incremental output
chunks and a `next_sequence` cursor.

File transfer deliberately reuses the same execution/policy path:

- `[@file.read, /path/to/file]`
- `[@file.list, /path/to/directory]`
- `[@file.write, /path/to/file]` with payload `{"content": "..."}`

Use `skill="filesystem"` when invoking these through a filesystem skill grant.
"""
