import sys

from agent_exec_gateway.executors import LocalExecutor


async def test_local_executor_emits_incremental_output():
    chunks: list[tuple[str, str]] = []

    async def capture(stream: str, text: str) -> None:
        chunks.append((stream, text))

    result = await LocalExecutor().execute(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ],
        None,
        timeout_seconds=5,
        on_output=capture,
    )

    assert result.exit_code == 0
    assert "out" in result.stdout
    assert "err" in result.stderr
    assert any(stream == "stdout" and "out" in data for stream, data in chunks)
    assert any(stream == "stderr" and "err" in data for stream, data in chunks)
