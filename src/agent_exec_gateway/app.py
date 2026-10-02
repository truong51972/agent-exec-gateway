from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import MCPRequestContextMiddleware
from .db import init_db
from .mcp_server import mcp
from .web import router

raw_mcp_app = mcp.streamable_http_app(streamable_http_path="/")
mcp_app = MCPRequestContextMiddleware(raw_mcp_app)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Agent Exec Gateway",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(router)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)
app.mount("/mcp", mcp_app)
