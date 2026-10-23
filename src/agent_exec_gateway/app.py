from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import MCPRequestContextMiddleware
from .db import init_db
from .mcp_server import mcp
from .web import router


def create_app() -> FastAPI:
    """Create one independent ASGI application and MCP HTTP session manager."""
    raw_mcp_app = mcp.streamable_http_app(streamable_http_path="/")
    session_manager = mcp.session_manager
    mcp_app = MCPRequestContextMiddleware(raw_mcp_app)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await init_db()
        async with session_manager.run():
            yield

    application = FastAPI(
        title="Agent Exec Gateway",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.include_router(router)
    application.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    application.mount("/mcp", mcp_app)
    return application


app = create_app()
