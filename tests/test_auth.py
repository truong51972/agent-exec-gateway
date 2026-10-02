from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_exec_gateway.auth import ClientService
from agent_exec_gateway.models import Base


async def test_client_tokens_are_resolved_without_storing_raw_token():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        created = await ClientService(session).create("chatgpt")
        assert created.token
        assert created.token_prefix == created.token[:8]

        client_name, session_id = await ClientService(session).resolve(
            created.token,
            protocol="mcp",
            external_session_id="session-1",
        )
        assert client_name == "chatgpt"
        assert session_id is not None

    await engine.dispose()
