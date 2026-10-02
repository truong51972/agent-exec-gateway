import sys

from agent_exec_gateway.executors import LocalExecutor


async def test_local_executor_uses_structured_argv():
    result = await LocalExecutor().execute(
        [sys.executable, "-c", "print('hello')"], cwd=None, timeout_seconds=5
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
