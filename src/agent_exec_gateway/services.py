from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .executors import executor_for
from .models import Approval, Execution, Host
from .policy import PolicyEngine
from .schemas import ExecRead, ExecRequest

settings = get_settings()


class ExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def submit(self, request: ExecRequest, *, client: str) -> ExecRead:
        host = await self.session.scalar(select(Host).where(Host.name == request.host))
        if host is None or not host.enabled:
            raise ValueError(f"unknown or disabled host: {request.host}")

        policy = await PolicyEngine(
            self.session, default_decision=settings.default_decision
        ).evaluate(client=client, host=host.name, argv=request.argv)

        status = {
            "allow": "running",
            "ask": "awaiting_approval",
            "deny": "denied",
        }[policy.decision]
        execution = Execution(
            client=client,
            host_name=host.name,
            cwd=request.cwd,
            argv=request.argv,
            decision=policy.decision,
            status=status,
        )
        self.session.add(execution)
        await self.session.flush()

        if policy.decision == "ask":
            self.session.add(Approval(execution_id=execution.id))
            await self.session.commit()
            await self.session.refresh(execution)
            return ExecRead.model_validate(execution)

        if policy.decision == "deny":
            execution.completed_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(execution)
            return ExecRead.model_validate(execution)

        await self.session.commit()
        return await self._run(execution, host)

    async def approve(self, execution_id: str) -> ExecRead:
        execution = await self.session.get(Execution, execution_id)
        if execution is None:
            raise ValueError("execution not found")
        approval = await self.session.scalar(
            select(Approval).where(Approval.execution_id == execution_id)
        )
        if approval is None or approval.status != "pending":
            raise ValueError("execution has no pending approval")
        host = await self.session.scalar(select(Host).where(Host.name == execution.host_name))
        if host is None or not host.enabled:
            raise ValueError("execution host is unavailable")

        approval.status = "approved"
        approval.decided_at = datetime.now(UTC)
        execution.status = "running"
        await self.session.commit()
        return await self._run(execution, host)

    async def deny(self, execution_id: str) -> ExecRead:
        execution = await self.session.get(Execution, execution_id)
        if execution is None:
            raise ValueError("execution not found")
        approval = await self.session.scalar(
            select(Approval).where(Approval.execution_id == execution_id)
        )
        if approval is None or approval.status != "pending":
            raise ValueError("execution has no pending approval")

        now = datetime.now(UTC)
        approval.status = "denied"
        approval.decided_at = now
        execution.status = "denied"
        execution.completed_at = now
        await self.session.commit()
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)

    async def get(self, execution_id: str) -> ExecRead | None:
        execution = await self.session.get(Execution, execution_id)
        return ExecRead.model_validate(execution) if execution else None

    async def _run(self, execution: Execution, host: Host) -> ExecRead:
        try:
            result = await executor_for(host).execute(
                execution.argv,
                execution.cwd,
                timeout_seconds=settings.execution_timeout_seconds,
            )
            execution.exit_code = result.exit_code
            execution.stdout = result.stdout
            execution.stderr = result.stderr
            execution.status = "completed"
        except TimeoutError:
            execution.status = "timed_out"
            execution.stderr = "execution timed out"
        except Exception as exc:  # execution failures are audit data, not server failures
            execution.status = "failed"
            execution.stderr = f"{type(exc).__name__}: {exc}"
        execution.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)
