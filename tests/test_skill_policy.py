from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_exec_gateway.models import Base, SkillGrant
from agent_exec_gateway.policy import PolicyEngine


async def test_skill_grant_only_applies_inside_skill_permission():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        session.add(
            SkillGrant(
                client="chatgpt",
                host="workstation",
                skill="git-read",
                decision="allow",
            )
        )
        await session.commit()

        allowed = await PolicyEngine(session).evaluate(
            client="chatgpt",
            host="workstation",
            argv=["git", "status"],
            skill="git-read",
        )
        escaped = await PolicyEngine(session).evaluate(
            client="chatgpt",
            host="workstation",
            argv=["git", "push"],
            skill="git-read",
        )

        assert allowed.decision == "allow"
        assert allowed.source == "skill_grant"
        assert escaped.decision == "deny"

    await engine.dispose()
