import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_exec_gateway.models import Base, Policy
from agent_exec_gateway.policy import PolicyEngine


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as value:
        yield value
    await engine.dispose()


async def test_default_is_ask(session):
    result = await PolicyEngine(session).evaluate(
        client="mcp", host="local", argv=["git", "status"]
    )
    assert result.decision == "ask"
    assert result.policy_id is None


async def test_more_specific_rule_wins(session):
    session.add_all(
        [
            Policy(command="git", decision="ask"),
            Policy(command="git", args_prefix=["status"], decision="allow"),
            Policy(command="sudo", decision="deny"),
        ]
    )
    await session.commit()

    status = await PolicyEngine(session).evaluate(
        client="mcp", host="local", argv=["git", "status", "--short"]
    )
    push = await PolicyEngine(session).evaluate(
        client="mcp", host="local", argv=["git", "push"]
    )
    sudo = await PolicyEngine(session).evaluate(
        client="mcp", host="local", argv=["sudo", "true"]
    )

    assert status.decision == "allow"
    assert push.decision == "ask"
    assert sudo.decision == "deny"
