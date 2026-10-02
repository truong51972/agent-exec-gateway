import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import asyncssh

from .models import Host


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


class Executor(Protocol):
    async def execute(
        self, argv: list[str], cwd: str | None, *, timeout_seconds: float
    ) -> ExecResult: ...


class LocalExecutor:
    async def execute(
        self, argv: list[str], cwd: str | None, *, timeout_seconds: float
    ) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        return ExecResult(
            exit_code=process.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )


class SSHExecutor:
    def __init__(self, host: Host) -> None:
        self.host = host

    async def execute(
        self, argv: list[str], cwd: str | None, *, timeout_seconds: float
    ) -> ExecResult:
        if not self.host.hostname:
            raise ValueError("SSH host is missing hostname")

        command = shlex.join(argv)
        if cwd:
            command = f"cd {shlex.quote(cwd)} && exec {command}"

        connect_kwargs: dict[str, object] = {
            "host": self.host.hostname,
            "port": self.host.port,
            "username": self.host.username,
            "known_hosts": str(Path.home() / ".ssh" / "known_hosts"),
        }
        if self.host.identity_file:
            connect_kwargs["client_keys"] = [self.host.identity_file]

        async with asyncssh.connect(**connect_kwargs) as connection:
            result = await asyncio.wait_for(
                connection.run(command, check=False), timeout=timeout_seconds
            )

        return ExecResult(
            exit_code=result.exit_status,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def executor_for(host: Host) -> Executor:
    if host.transport == "local":
        return LocalExecutor()
    if host.transport == "ssh":
        return SSHExecutor(host)
    raise ValueError(f"unsupported transport: {host.transport}")
