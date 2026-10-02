import hashlib
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Client, Session
from .schemas import ClientCreated, ClientRead

settings = get_settings()


@dataclass(frozen=True)
class RequestIdentity:
    bearer_token: str | None = None
    external_session_id: str | None = None


mcp_request_identity: ContextVar[RequestIdentity | None] = ContextVar(
    "mcp_request_identity", default=None
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_from_headers(headers: list[tuple[bytes, bytes]]) -> str | None:
    values = {key.lower(): value for key, value in headers}
    authorization = values.get(b"authorization")
    if not authorization:
        return None
    text = authorization.decode(errors="ignore")
    scheme, _, token = text.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


class MCPRequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        token = bearer_from_headers(headers)
        external_session_id = None
        for key, value in headers:
            if key.lower() == b"mcp-session-id":
                external_session_id = value.decode(errors="ignore")
                break

        if settings.mcp_auth_required and not token:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"MCP bearer token required"}',
                }
            )
            return

        context_token = mcp_request_identity.set(
            RequestIdentity(
                bearer_token=token,
                external_session_id=external_session_id,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            mcp_request_identity.reset(context_token)


class ClientService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, name: str) -> ClientCreated:
        token = secrets.token_urlsafe(32)
        model = Client(
            name=name,
            token_hash=hash_token(token),
            token_prefix=token[:8],
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return ClientCreated(
            **ClientRead.model_validate(model).model_dump(),
            token=token,
        )

    async def resolve(
        self,
        token: str | None,
        *,
        protocol: str,
        external_session_id: str | None = None,
    ) -> tuple[str, str | None]:
        if token:
            client = await self.session.scalar(
                select(Client).where(
                    Client.token_hash == hash_token(token),
                    Client.enabled.is_(True),
                )
            )
            if client is None:
                raise PermissionError("invalid or disabled client token")
            client_name = client.name
        elif settings.mcp_auth_required and protocol == "mcp":
            raise PermissionError("MCP authentication is required")
        else:
            client_name = "anonymous" if protocol == "mcp" else protocol

        session_id = None
        if external_session_id:
            existing = await self.session.scalar(
                select(Session).where(
                    Session.client_name == client_name,
                    Session.protocol == protocol,
                    Session.external_id == external_session_id,
                )
            )
            now = datetime.now(UTC)
            if existing is None:
                existing = Session(
                    client_name=client_name,
                    protocol=protocol,
                    external_id=external_session_id,
                    last_seen_at=now,
                )
                self.session.add(existing)
            else:
                existing.last_seen_at = now
            await self.session.commit()
            await self.session.refresh(existing)
            session_id = existing.id

        return client_name, session_id

    async def rotate(self, client: Client) -> ClientCreated:
        token = secrets.token_urlsafe(32)
        client.token_hash = hash_token(token)
        client.token_prefix = token[:8]
        await self.session.commit()
        await self.session.refresh(client)
        return ClientCreated(
            **ClientRead.model_validate(client).model_dump(),
            token=token,
        )
