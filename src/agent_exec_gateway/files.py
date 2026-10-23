import asyncio
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from .executors import SSHExecutor
from .models import Host


@dataclass(frozen=True)
class FileResult:
    output: str


def _read_local(path: str) -> str:
    return Path(path).expanduser().read_text()


def _write_local(path: str, content: str) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def _list_local(path: str) -> list[str]:
    return sorted(item.name for item in Path(path).expanduser().iterdir())


class FileTransport:
    async def read_text(self, host: Host, path: str) -> FileResult:
        if host.transport == "local":
            content = await asyncio.to_thread(_read_local, path)
            return FileResult(content)

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                async with sftp.open(path, "r") as remote:
                    content = await remote.read()
        return FileResult(str(content))

    async def write_text(self, host: Host, path: str, content: str) -> FileResult:
        if host.transport == "local":
            await asyncio.to_thread(_write_local, path, content)
            return FileResult(f"wrote {len(content)} characters to {path}")

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                async with sftp.open(path, "w") as remote:
                    await remote.write(content)
        return FileResult(f"wrote {len(content)} characters to {path}")

    async def list_dir(self, host: Host, path: str) -> FileResult:
        if host.transport == "local":
            entries = await asyncio.to_thread(_list_local, path)
            return FileResult("\n".join(entries))

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                entries = sorted(await sftp.listdir(path))
        return FileResult("\n".join(entries))
