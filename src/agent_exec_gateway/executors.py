import asyncio
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import asyncssh

from .models import Host

OutputCallback = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


class Executor(Protocol):
    async def execute(
        self,
        argv: list[str],
        cwd: str | None,
        *,
        timeout_seconds: float,
        on_output: OutputCallback | None = None,
    ) -> ExecResult: ...


class LocalExecutor:
    async def execute(
        self,
        argv: list[str],
        cwd: str | None,
        *,
        timeout_seconds: float,
        on_output: OutputCallback | None = None,
    ) -> ExecResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async def pump(
            stream: asyncio.StreamReader | None,
            stream_name: str,
            output: list[str],
        ) -> None:
            if stream is None:
                return
            while chunk := await stream.read(4096):
                text = chunk.decode(errors="replace")
                output.append(text)
                if on_output:
                    await on_output(stream_name, text)

        try:
            async with asyncio.timeout(timeout_seconds):
                await asyncio.gather(
                    pump(process.stdout, "stdout", stdout_parts),
                    pump(process.stderr, "stderr", stderr_parts),
                    process.wait(),
                )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise

        return ExecResult(
            exit_code=process.returncode or 0,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
        )


class SSHExecutor:
    def __init__(self, host: Host) -> None:
        self.host = host

    def _connect_kwargs(self) -> dict[str, object]:
        if not self.host.hostname:
            raise ValueError("SSH host is missing hostname")
        kwargs: dict[str, object] = {
            "host": self.host.hostname,
            "port": self.host.port,
            "username": self.host.username,
            "known_hosts": str(Path.home() / ".ssh" / "known_hosts"),
        }
        if self.host.identity_file:
            kwargs["client_keys"] = [self.host.identity_file]
        return kwargs

    async def execute(
        self,
        argv: list[str],
        cwd: str | None,
        *,
        timeout_seconds: float,
        on_output: OutputCallback | None = None,
    ) -> ExecResult:
        command = shlex.join(argv)
        if cwd:
            command = f"cd {shlex.quote(cwd)} && exec {command}"

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async with asyncssh.connect(**self._connect_kwargs()) as connection:
            process = await connection.create_process(command)

            async def pump(reader, stream_name: str, output: list[str]) -> None:
                async for chunk in reader:
                    text = str(chunk)
                    output.append(text)
                    if on_output:
                        await on_output(stream_name, text)

            try:
                async with asyncio.timeout(timeout_seconds):
                    await asyncio.gather(
                        pump(process.stdout, "stdout", stdout_parts),
                        pump(process.stderr, "stderr", stderr_parts),
                        process.wait(),
                    )
            except TimeoutError:
                process.terminate()
                raise

        return ExecResult(
            exit_code=process.exit_status if process.exit_status is not None else -1,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
        )

    async def command_exists(self, command: str) -> bool:
        probe = f"command -v {shlex.quote(command)} >/dev/null 2>&1"
        async with asyncssh.connect(**self._connect_kwargs()) as connection:
            result = await connection.run(probe, check=False)
        return result.exit_status == 0


def executor_for(host: Host) -> Executor:
    if host.transport == "local":
        return LocalExecutor()
    if host.transport == "ssh":
        return SSHExecutor(host)
    raise ValueError(f"unsupported transport: {host.transport}")
