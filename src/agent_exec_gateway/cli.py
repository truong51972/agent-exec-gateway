import typer
import uvicorn

from .config import get_settings

app = typer.Typer(no_args_is_help=True, help="Agent Exec Gateway")


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind address"),
    port: int | None = typer.Option(None, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable Uvicorn auto-reload"),
) -> None:
    """Serve dashboard, REST API, and MCP from one ASGI process."""
    settings = get_settings()
    uvicorn.run(
        "agent_exec_gateway.app:app",
        host=host or settings.bind_host,
        port=port or settings.port,
        reload=reload,
    )
