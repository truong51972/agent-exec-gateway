import asyncio
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

import asyncssh
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import AuditService
from .config import get_settings
from .executors import SSHExecutor, executor_for
from .models import Host
from .schemas import (
    HostCreate,
    HostRead,
    HostTestResult,
    HostUpdate,
    PairingInfo,
)
from .skills import CapabilityService, registry

settings = get_settings()


class HostService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[HostRead]:
        rows = (await self.session.scalars(select(Host).order_by(Host.name))).all()
        return [HostRead.model_validate(item) for item in rows]

    async def get_model(self, name: str) -> Host:
        host = await self.session.scalar(select(Host).where(Host.name == name))
        if host is None:
            raise ValueError(f"host not found: {name}")
        return host

    async def create(self, payload: HostCreate, *, actor: str = "dashboard") -> HostRead:
        host = Host(**payload.model_dump())
        self.session.add(host)
        await AuditService(self.session).record(
            "host.created",
            actor=actor,
            host_name=host.name,
            details={"transport": host.transport, "hostname": host.hostname},
        )
        await self.session.commit()
        await self.session.refresh(host)
        return HostRead.model_validate(host)

    async def update(
        self,
        name: str,
        payload: HostUpdate,
        *,
        actor: str = "dashboard",
    ) -> HostRead:
        host = await self.get_model(name)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(host, field, value)
        await AuditService(self.session).record(
            "host.updated",
            actor=actor,
            host_name=name,
            details=payload.model_dump(exclude_unset=True),
        )
        await self.session.commit()
        await self.session.refresh(host)
        return HostRead.model_validate(host)

    async def delete(self, name: str, *, actor: str = "dashboard") -> None:
        if name == "local":
            raise ValueError("the built-in local host cannot be deleted")
        host = await self.get_model(name)
        await AuditService(self.session).record(
            "host.deleted",
            actor=actor,
            host_name=name,
        )
        await self.session.delete(host)
        await self.session.execute(delete_capabilities_statement(name))
        await self.session.commit()

    async def pairing_info(
        self,
        name: str,
        *,
        actor: str = "dashboard",
    ) -> PairingInfo:
        host = await self.get_model(name)
        if host.transport != "ssh":
            raise ValueError("pairing keys only apply to SSH hosts")

        key_path = settings.data_dir / "keys" / f"{safe_name(name)}.ed25519"
        public_key = await asyncio.to_thread(ensure_keypair, key_path)
        host.identity_file = str(key_path)
        await AuditService(self.session).record(
            "host.pairing_key.generated",
            actor=actor,
            host_name=name,
            details={"identity_file": str(key_path)},
        )
        await self.session.commit()

        quoted_key = shlex.quote(public_key)
        install_command = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"printf '%s\\n' {quoted_key} >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys"
        )
        return PairingInfo(
            host=name,
            identity_file=str(key_path),
            public_key=public_key,
            install_command=install_command,
        )

    async def test(self, name: str) -> HostTestResult:
        host = await self.get_model(name)
        try:
            result = await executor_for(host).execute(
                ["true"] if host.transport == "ssh" else [sys.executable, "-c", "pass"],
                None,
                timeout_seconds=min(settings.execution_timeout_seconds, 15.0),
            )
            ok = result.exit_code == 0
            message = "connection successful" if ok else result.stderr or "command failed"
        except Exception as exc:
            ok = False
            message = f"{type(exc).__name__}: {exc}"
        return HostTestResult(host=name, ok=ok, message=message)

    async def scan_capabilities(self, name: str):
        host = await self.get_model(name)
        results: list[tuple[str, bool, dict]] = []

        for skill in registry.list():
            command_results: dict[str, bool] = {}
            for command in skill.requires_commands:
                if host.transport == "local":
                    exists = await asyncio.to_thread(shutil.which, command)
                    command_results[command] = exists is not None
                else:
                    exists = await SSHExecutor(host).command_exists(command)
                    command_results[command] = exists
            available = all(command_results.values())
            results.append((skill.name, available, {"commands": command_results}))

        rows = await CapabilityService(self.session).replace(host, results)
        await AuditService(self.session).record(
            "host.capabilities.scanned",
            actor="dashboard",
            host_name=name,
            details={
                "available": [row.skill for row in rows if row.available],
                "count": len(rows),
            },
            commit=True,
        )
        return rows


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


def ensure_keypair(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        private_key = asyncssh.read_private_key(str(path))
    else:
        private_key = asyncssh.generate_private_key("ssh-ed25519")
        path.write_bytes(private_key.export_private_key("openssh"))
        os.chmod(path, 0o600)

    public = private_key.export_public_key("openssh")
    if isinstance(public, bytes):
        return public.decode().strip()
    return str(public).strip()


def delete_capabilities_statement(host_name: str):
    from .models import HostCapability

    return delete(HostCapability).where(HostCapability.host_name == host_name)
