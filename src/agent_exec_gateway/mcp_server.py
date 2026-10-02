from sqlalchemy import select

from mcp.server import MCPServer

from .db import SessionLocal
from .models import Host
from .schemas import ExecRequest, HostRead
from .services import ExecutionService

mcp = MCPServer("Agent Exec Gateway")


@mcp.tool()
async def exec(host: str, argv: list[str], cwd: str | None = None) -> dict:
    """Execute structured argv on a managed host subject to gateway policy."""
    async with SessionLocal() as session:
        result = await ExecutionService(session).submit(
            ExecRequest(host=host, argv=argv, cwd=cwd), client="mcp"
        )
        return result.model_dump(mode="json")


@mcp.tool()
async def execution_status(execution_id: str) -> dict:
    """Return the current state and output of an execution."""
    async with SessionLocal() as session:
        result = await ExecutionService(session).get(execution_id)
        if result is None:
            return {"error": "execution not found", "execution_id": execution_id}
        return result.model_dump(mode="json")


@mcp.tool()
async def hosts() -> list[dict]:
    """List enabled execution hosts."""
    async with SessionLocal() as session:
        items = (
            await session.scalars(select(Host).where(Host.enabled.is_(True)).order_by(Host.name))
        ).all()
        return [HostRead.model_validate(item).model_dump(mode="json") for item in items]
