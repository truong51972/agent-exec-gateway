from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .mcp_server import mcp
from .web import router

mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Agent Exec Gateway",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
app.mount("/mcp", mcp_app)
