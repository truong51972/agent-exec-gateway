from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        event_type: str,
        *,
        actor: str,
        host_name: str | None = None,
        execution_id: str | None = None,
        details: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            actor=actor,
            host_name=host_name,
            execution_id=execution_id,
            details=details or {},
        )
        self.session.add(event)
        if commit:
            await self.session.commit()
            await self.session.refresh(event)
        else:
            await self.session.flush()
        return event
