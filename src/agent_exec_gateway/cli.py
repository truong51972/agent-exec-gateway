import asyncio

import typer
import uvicorn
from sqlalchemy import select

from .auth import ClientService
from .config import get_settings
from .db import SessionLocal, init_db
from .hosts import HostService
from .models import Client
from .schemas import HostCreate
from .skills import registry

app = typer.Typer(no_args_is_help=True, help="Agent Exec Gateway")
host_app = typer.Typer(no_args_is_help=True, help="Manage execution hosts")
client_app = typer.Typer(no_args_is_help=True, help="Manage MCP/REST clients")
skill_app = typer.Typer(no_args_is_help=True, help="Inspect installed skills")
app.add_typer(host_app, name="host")
app.add_typer(client_app, name="client")
app.add_typer(skill_app, name="skill")


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


@host_app.command("add")
def host_add(
    name: str,
    hostname: str,
    username: str | None = typer.Option(None),
    port: int = typer.Option(22),
) -> None:
    """Register an SSH host."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            result = await HostService(session).create(
                HostCreate(
                    name=name,
                    hostname=hostname,
                    username=username,
                    port=port,
                    transport="ssh",
                ),
                actor="cli",
            )
            typer.echo(f"Added {result.name} -> {result.hostname}:{result.port}")

    asyncio.run(run())


@host_app.command("pairing")
def host_pairing(name: str) -> None:
    """Generate/reuse a gateway SSH key and print the one-time install command."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            info = await HostService(session).pairing_info(name, actor="cli")
            typer.echo(f"Identity: {info.identity_file}")
            typer.echo(f"Public key: {info.public_key}")
            typer.echo("\nRun once on the target host:")
            typer.echo(info.install_command)

    asyncio.run(run())


@host_app.command("test")
def host_test(name: str) -> None:
    """Test local/SSH execution on a host."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            result = await HostService(session).test(name)
            if not result.ok:
                typer.echo(result.message, err=True)
                raise typer.Exit(code=1)
            typer.echo(result.message)

    asyncio.run(run())


@host_app.command("scan")
def host_scan(name: str) -> None:
    """Detect which installed skills are available on a host."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            rows = await HostService(session).scan_capabilities(name)
            for row in rows:
                marker = "✓" if row.available else "✗"
                typer.echo(f"{marker} {row.skill}")

    asyncio.run(run())


@client_app.command("create")
def client_create(name: str) -> None:
    """Create a client token. The raw token is printed only once."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            created = await ClientService(session).create(name)
            typer.echo(f"Client: {created.name}")
            typer.echo(f"Token: {created.token}")

    asyncio.run(run())


@client_app.command("rotate")
def client_rotate(name: str) -> None:
    """Rotate a client token and print the replacement once."""

    async def run() -> None:
        await init_db()
        async with SessionLocal() as session:
            client = await session.scalar(select(Client).where(Client.name == name))
            if client is None:
                typer.echo("client not found", err=True)
                raise typer.Exit(code=1)
            rotated = await ClientService(session).rotate(client)
            typer.echo(f"Token: {rotated.token}")

    asyncio.run(run())


@skill_app.command("list")
def skill_list() -> None:
    """List skills shipped with the gateway."""
    for skill in registry.list():
        requires = ", ".join(skill.requires_commands) or "none"
        typer.echo(f"{skill.name}: {skill.description} [requires: {requires}]")
