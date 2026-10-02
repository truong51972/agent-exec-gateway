import asyncio
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from .executors import SSHExecutor
from .models import Host


@dataclass(frozen=True)
class FileResult:
    output: str


class FileTransport:
    async def read_text(self, host: Host, path: str) -> FileResult:
        if host.transport == "local":
            content = await asyncio.to_thread(Path(path).expanduser().read_text)
            return FileResult(content)

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                async with sftp.open(path, "r") as remote:
                    content = await remote.read()
        return FileResult(str(content))

    async def write_text(self, host: Host, path: str, content: str) -> FileResult:
        if host.transport == "local":
            target = Path(path).expanduser()

            def write() -> None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

            await asyncio.to_thread(write)
            return FileResult(f"wrote {len(content)} characters to {path}")

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                async with sftp.open(path, "w") as remote:
                    await remote.write(content)
        return FileResult(f"wrote {len(content)} characters to {path}")

    async def list_dir(self, host: Host, path: str) -> FileResult:
        if host.transport == "local":
            entries = await asyncio.to_thread(
                lambda: sorted(item.name for item in Path(path).expanduser().iterdir())
            )
            return FileResult("\n".join(entries))

        ssh = SSHExecutor(host)
        async with asyncssh.connect(**ssh._connect_kwargs()) as connection:
            async with connection.start_sftp_client() as sftp:
                entries = sorted(await sftp.listdir(path))
        return FileResult("\n".join(entries))
