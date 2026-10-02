import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import AuditService
from .config import get_settings
from .executors import executor_for
from .files import FileTransport
from .models import (
    Approval,
    Execution,
    ExecutionChunk,
    ExecutionContext,
    Host,
    Policy,
    SkillGrant,
)
from .policy import PolicyEngine
from .schemas import (
    ExecRead,
    ExecRequest,
    ExecutionChunkRead,
    ExecutionContextRead,
    ExecutionStatusRead,
)

settings = get_settings()


class ExecutionDispatcher:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    def start(self, execution_id: str) -> None:
        task = asyncio.create_task(self._run(execution_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _run(self, execution_id: str) -> None:
        from .db import SessionLocal

        async with SessionLocal() as session:
            await ExecutionService(session)._run_by_id(execution_id)


dispatcher = ExecutionDispatcher()


class ExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def submit(
        self,
        request: ExecRequest,
        *,
        client: str,
        session_id: str | None = None,
    ) -> ExecRead:
        host = await self.session.scalar(select(Host).where(Host.name == request.host))
        if host is None or not host.enabled:
            raise ValueError(f"unknown or disabled host: {request.host}")

        policy = await PolicyEngine(
            self.session,
            default_decision=settings.default_decision,
        ).evaluate(
            client=client,
            host=host.name,
            argv=request.argv,
            skill=request.skill,
        )

        status = {
            "allow": "queued" if not request.wait else "running",
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

        context = ExecutionContext(
            execution_id=execution.id,
            session_id=session_id,
            skill=request.skill,
            policy_source=policy.source,
            policy_ref=policy.reference,
            input_payload=request.payload,
        )
        self.session.add(context)
        await AuditService(self.session).record(
            "execution.requested",
            actor=client,
            host_name=host.name,
            execution_id=execution.id,
            details={
                "argv": request.argv,
                "cwd": request.cwd,
                "skill": request.skill,
                "decision": policy.decision,
                "policy_source": policy.source,
                "policy_ref": policy.reference,
            },
        )

        if policy.decision == "ask":
            self.session.add(Approval(execution_id=execution.id))
            await self.session.commit()
            await self.session.refresh(execution)
            return ExecRead.model_validate(execution)

        if policy.decision == "deny":
            execution.completed_at = datetime.now(UTC)
            await AuditService(self.session).record(
                "execution.denied",
                actor=client,
                host_name=host.name,
                execution_id=execution.id,
            )
            await self.session.commit()
            await self.session.refresh(execution)
            return ExecRead.model_validate(execution)

        await self.session.commit()
        if request.wait:
            return await self._run_by_id(execution.id)

        dispatcher.start(execution.id)
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)

    async def approve(
        self,
        execution_id: str,
        *,
        actor: str = "dashboard",
        always_allow: bool = False,
        wait: bool = True,
    ) -> ExecRead:
        execution = await self._get_execution(execution_id)
        approval = await self.session.scalar(
            select(Approval).where(Approval.execution_id == execution_id)
        )
        if approval is None or approval.status != "pending":
            raise ValueError("execution has no pending approval")

        host = await self.session.scalar(select(Host).where(Host.name == execution.host_name))
        if host is None or not host.enabled:
            raise ValueError("execution host is unavailable")

        context = await self.session.get(ExecutionContext, execution_id)
        now = datetime.now(UTC)
        approval.status = "approved"
        approval.decided_at = now
        execution.status = "running" if wait else "queued"

        if always_allow:
            await self._create_allow_rule(execution, context)

        await AuditService(self.session).record(
            "execution.approved",
            actor=actor,
            host_name=execution.host_name,
            execution_id=execution.id,
            details={"always_allow": always_allow},
        )
        await self.session.commit()

        if wait:
            return await self._run_by_id(execution.id)
        dispatcher.start(execution.id)
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)

    async def deny(
        self,
        execution_id: str,
        *,
        actor: str = "dashboard",
    ) -> ExecRead:
        execution = await self._get_execution(execution_id)
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
        await AuditService(self.session).record(
            "execution.approval_denied",
            actor=actor,
            host_name=execution.host_name,
            execution_id=execution.id,
        )
        await self.session.commit()
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)

    async def get(self, execution_id: str) -> ExecRead | None:
        execution = await self.session.get(Execution, execution_id)
        return ExecRead.model_validate(execution) if execution else None

    async def status(
        self,
        execution_id: str,
        *,
        after_sequence: int = 0,
    ) -> ExecutionStatusRead | None:
        execution = await self.session.get(Execution, execution_id)
        if execution is None:
            return None
        context = await self.session.get(ExecutionContext, execution_id)
        chunks = (
            await self.session.scalars(
                select(ExecutionChunk)
                .where(
                    ExecutionChunk.execution_id == execution_id,
                    ExecutionChunk.sequence > after_sequence,
                )
                .order_by(ExecutionChunk.sequence)
            )
        ).all()
        chunk_reads = [ExecutionChunkRead.model_validate(item) for item in chunks]
        next_sequence = chunk_reads[-1].sequence if chunk_reads else after_sequence
        return ExecutionStatusRead(
            execution=ExecRead.model_validate(execution),
            context=(
                ExecutionContextRead.model_validate(context)
                if context is not None
                else None
            ),
            chunks=chunk_reads,
            next_sequence=next_sequence,
        )

    async def _get_execution(self, execution_id: str) -> Execution:
        execution = await self.session.get(Execution, execution_id)
        if execution is None:
            raise ValueError("execution not found")
        return execution

    async def _create_allow_rule(
        self,
        execution: Execution,
        context: ExecutionContext | None,
    ) -> None:
        if context is not None and context.skill:
            self.session.add(
                SkillGrant(
                    client=execution.client,
                    host=execution.host_name,
                    skill=context.skill,
                    decision="allow",
                )
            )
            return

        self.session.add(
            Policy(
                client=execution.client,
                host=execution.host_name,
                command=execution.argv[0],
                args_prefix=execution.argv[1:],
                decision="allow",
            )
        )

    async def _run_by_id(self, execution_id: str) -> ExecRead:
        execution = await self._get_execution(execution_id)
        host = await self.session.scalar(select(Host).where(Host.name == execution.host_name))
        if host is None or not host.enabled:
            execution.status = "failed"
            execution.stderr = "execution host is unavailable"
            execution.completed_at = datetime.now(UTC)
            await self.session.commit()
            return ExecRead.model_validate(execution)

        context = await self.session.get(ExecutionContext, execution_id)
        execution.status = "running"
        await self.session.commit()

        current_sequence = (
            await self.session.scalar(
                select(func.max(ExecutionChunk.sequence)).where(
                    ExecutionChunk.execution_id == execution_id
                )
            )
            or 0
        )
        captured_chars = 0

        async def on_output(stream: str, text: str) -> None:
            nonlocal current_sequence, captured_chars
            remaining = settings.max_output_chars - captured_chars
            if remaining <= 0:
                return
            clipped = text[:remaining]
            if not clipped:
                return
            current_sequence += 1
            captured_chars += len(clipped)
            self.session.add(
                ExecutionChunk(
                    execution_id=execution_id,
                    sequence=current_sequence,
                    stream=stream,
                    data=clipped,
                )
            )
            await self.session.commit()

        try:
            if execution.argv[0].startswith("@file."):
                result = await self._run_file_operation(execution, host, context, on_output)
                execution.exit_code = 0
                execution.stdout = result[: settings.max_output_chars]
                execution.stderr = ""
            else:
                result = await executor_for(host).execute(
                    execution.argv,
                    execution.cwd,
                    timeout_seconds=settings.execution_timeout_seconds,
                    on_output=on_output,
                )
                execution.exit_code = result.exit_code
                execution.stdout = result.stdout[: settings.max_output_chars]
                execution.stderr = result.stderr[: settings.max_output_chars]
            execution.status = "completed"
        except TimeoutError:
            execution.status = "timed_out"
            execution.stderr = "execution timed out"
        except Exception as exc:
            execution.status = "failed"
            execution.stderr = f"{type(exc).__name__}: {exc}"

        execution.completed_at = datetime.now(UTC)
        await AuditService(self.session).record(
            "execution.completed",
            actor=execution.client,
            host_name=execution.host_name,
            execution_id=execution.id,
            details={"status": execution.status, "exit_code": execution.exit_code},
        )
        await self.session.commit()
        await self.session.refresh(execution)
        return ExecRead.model_validate(execution)

    async def _run_file_operation(
        self,
        execution: Execution,
        host: Host,
        context: ExecutionContext | None,
        on_output,
    ) -> str:
        if len(execution.argv) < 2:
            raise ValueError("file operations require a path")
        operation, path = execution.argv[0], execution.argv[1]
        files = FileTransport()

        if operation == "@file.read":
            result = await files.read_text(host, path)
        elif operation == "@file.list":
            result = await files.list_dir(host, path)
        elif operation == "@file.write":
            payload = context.input_payload if context is not None else {}
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError("@file.write requires payload.content")
            result = await files.write_text(host, path, content)
        else:
            raise ValueError(f"unsupported file operation: {operation}")

        await on_output("stdout", result.output)
        return result.output
