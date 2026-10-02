from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Approval, Execution, Host, Policy
from .schemas import ApprovalRead, ExecRead, ExecRequest, HostCreate, HostRead, PolicyCreate, PolicyRead
from .services import ExecutionService

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    hosts = (await session.scalars(select(Host).order_by(Host.name))).all()
    approvals = (
        await session.scalars(
            select(Approval).where(Approval.status == "pending").order_by(Approval.created_at.desc())
        )
    ).all()
    executions = (
        await session.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(20))
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"hosts": hosts, "approvals": approvals, "executions": executions},
    )


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/hosts", response_model=list[HostRead])
async def list_hosts(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Host).order_by(Host.name))).all()


@router.post("/api/hosts", response_model=HostRead, status_code=201)
async def create_host(payload: HostCreate, session: AsyncSession = Depends(get_session)):
    host = Host(**payload.model_dump())
    session.add(host)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="host already exists or is invalid") from exc
    await session.refresh(host)
    return host


@router.get("/api/policies", response_model=list[PolicyRead])
async def list_policies(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Policy).order_by(Policy.id))).all()


@router.post("/api/policies", response_model=PolicyRead, status_code=201)
async def create_policy(payload: PolicyCreate, session: AsyncSession = Depends(get_session)):
    policy = Policy(**payload.model_dump())
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


@router.post("/api/executions", response_model=ExecRead)
async def execute(payload: ExecRequest, session: AsyncSession = Depends(get_session)):
    try:
        return await ExecutionService(session).submit(payload, client="rest")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/executions/{execution_id}", response_model=ExecRead)
async def execution(execution_id: str, session: AsyncSession = Depends(get_session)):
    result = await ExecutionService(session).get(execution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return result


@router.get("/api/approvals", response_model=list[ApprovalRead])
async def approvals(session: AsyncSession = Depends(get_session)):
    return (
        await session.scalars(select(Approval).order_by(Approval.created_at.desc()))
    ).all()


@router.post("/api/approvals/{execution_id}/approve", response_model=ExecRead)
async def approve(execution_id: str, session: AsyncSession = Depends(get_session)):
    try:
        return await ExecutionService(session).approve(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/approvals/{execution_id}/deny", response_model=ExecRead)
async def deny(execution_id: str, session: AsyncSession = Depends(get_session)):
    try:
        return await ExecutionService(session).deny(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
