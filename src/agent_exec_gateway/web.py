from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import ClientService
from .db import get_session
from .hosts import HostService
from .models import (
    Approval,
    AuditEvent,
    Client,
    Execution,
    Host,
    Policy,
    Session,
    SkillGrant,
)
from .schemas import (
    ApprovalRead,
    AuditEventRead,
    ClientCreate,
    ClientCreated,
    ClientRead,
    ClientUpdate,
    ExecRead,
    ExecRequest,
    ExecutionStatusRead,
    HostCapabilityRead,
    HostCreate,
    HostRead,
    HostTestResult,
    HostUpdate,
    PairingInfo,
    PolicyCreate,
    PolicyRead,
    SessionRead,
    SkillGrantCreate,
    SkillGrantRead,
    SkillSummary,
)
from .services import ExecutionService
from .skills import CapabilityService, registry

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


async def _request_principal(request: Request, session: AsyncSession) -> tuple[str, str | None]:
    return await ClientService(session).resolve(
        _bearer(request),
        protocol="rest",
        external_session_id=request.headers.get("x-aeg-session-id"),
    )


async def _dashboard_context(session: AsyncSession) -> dict:
    hosts = (await session.scalars(select(Host).order_by(Host.name))).all()
    approvals = (
        await session.scalars(
            select(Approval)
            .where(Approval.status == "pending")
            .order_by(Approval.created_at.desc())
        )
    ).all()
    executions = (
        await session.scalars(
            select(Execution).order_by(Execution.created_at.desc()).limit(25)
        )
    ).all()
    clients = (await session.scalars(select(Client).order_by(Client.name))).all()
    return {
        "hosts": hosts,
        "approvals": approvals,
        "executions": executions,
        "clients": clients,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: SessionDep):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=await _dashboard_context(session),
    )


@router.get("/hosts", response_class=HTMLResponse)
async def hosts_page(request: Request, session: SessionDep):
    hosts = (await session.scalars(select(Host).order_by(Host.name))).all()
    capabilities = {
        host.name: await CapabilityService(session).cached(host.name) for host in hosts
    }
    return templates.TemplateResponse(
        request=request,
        name="hosts.html",
        context={"hosts": hosts, "capabilities": capabilities},
    )


@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, session: SessionDep):
    clients = (await session.scalars(select(Client).order_by(Client.name))).all()
    sessions = (
        await session.scalars(select(Session).order_by(Session.last_seen_at.desc()).limit(50))
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context={"clients": clients, "sessions": sessions},
    )


@router.get("/policies", response_class=HTMLResponse)
async def policies_page(request: Request, session: SessionDep):
    policies = (await session.scalars(select(Policy).order_by(Policy.id.desc()))).all()
    grants = (
        await session.scalars(select(SkillGrant).order_by(SkillGrant.id.desc()))
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="policies.html",
        context={"policies": policies, "grants": grants, "skills": registry.list()},
    )


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request, session: SessionDep):
    hosts = (await session.scalars(select(Host).order_by(Host.name))).all()
    capabilities = {
        host.name: await CapabilityService(session).cached(host.name) for host in hosts
    }
    return templates.TemplateResponse(
        request=request,
        name="skills.html",
        context={"skills": registry.list(), "hosts": hosts, "capabilities": capabilities},
    )


@router.get("/approvals", response_class=HTMLResponse)
async def approvals_page(request: Request, session: SessionDep):
    approvals = (
        await session.scalars(select(Approval).order_by(Approval.created_at.desc()).limit(100))
    ).all()
    executions = {
        item.id: item
        for item in (
            await session.scalars(
                select(Execution).where(
                    Execution.id.in_([approval.execution_id for approval in approvals])
                )
            )
        ).all()
    }
    return templates.TemplateResponse(
        request=request,
        name="approvals.html",
        context={"approvals": approvals, "executions": executions},
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, session: SessionDep):
    events = (
        await session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)
        )
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={"events": events},
    )


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/hosts", response_model=list[HostRead])
async def list_hosts(session: SessionDep):
    return await HostService(session).list()


@router.post("/api/hosts", response_model=HostRead, status_code=201)
async def create_host(payload: HostCreate, session: SessionDep):
    try:
        return await HostService(session).create(payload)
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="host already exists or is invalid") from exc


@router.patch("/api/hosts/{name}", response_model=HostRead)
async def update_host(name: str, payload: HostUpdate, session: SessionDep):
    try:
        return await HostService(session).update(name, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/hosts/{name}", status_code=204)
async def delete_host(name: str, session: SessionDep):
    try:
        await HostService(session).delete(name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/hosts/{name}/pairing", response_model=PairingInfo)
async def host_pairing(name: str, session: SessionDep):
    try:
        return await HostService(session).pairing_info(name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/hosts/{name}/test", response_model=HostTestResult)
async def test_host(name: str, session: SessionDep):
    try:
        return await HostService(session).test(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/hosts/{name}/scan", response_model=list[HostCapabilityRead])
async def scan_host(name: str, session: SessionDep):
    try:
        return await HostService(session).scan_capabilities(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/hosts/{name}/capabilities", response_model=list[HostCapabilityRead])
async def host_capabilities(name: str, session: SessionDep):
    return await CapabilityService(session).cached(name)


@router.get("/api/clients", response_model=list[ClientRead])
async def list_clients(session: SessionDep):
    return (await session.scalars(select(Client).order_by(Client.name))).all()


@router.post("/api/clients", response_model=ClientCreated, status_code=201)
async def create_client(payload: ClientCreate, session: SessionDep):
    try:
        return await ClientService(session).create(payload.name)
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="client already exists") from exc


@router.patch("/api/clients/{name}", response_model=ClientRead)
async def update_client(name: str, payload: ClientUpdate, session: SessionDep):
    client = await session.scalar(select(Client).where(Client.name == name))
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    client.enabled = payload.enabled
    await session.commit()
    await session.refresh(client)
    return client


@router.post("/api/clients/{name}/rotate", response_model=ClientCreated)
async def rotate_client(name: str, session: SessionDep):
    client = await session.scalar(select(Client).where(Client.name == name))
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return await ClientService(session).rotate(client)


@router.get("/api/sessions", response_model=list[SessionRead])
async def list_sessions(session: SessionDep):
    return (
        await session.scalars(select(Session).order_by(Session.last_seen_at.desc()).limit(200))
    ).all()


@router.get("/api/policies", response_model=list[PolicyRead])
async def list_policies(session: SessionDep):
    return (await session.scalars(select(Policy).order_by(Policy.id))).all()


@router.post("/api/policies", response_model=PolicyRead, status_code=201)
async def create_policy(payload: PolicyCreate, session: SessionDep):
    policy = Policy(**payload.model_dump())
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


@router.delete("/api/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: int, session: SessionDep):
    result = await session.execute(delete(Policy).where(Policy.id == policy_id))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="policy not found")
    await session.commit()


@router.get("/api/skill-grants", response_model=list[SkillGrantRead])
async def list_skill_grants(session: SessionDep):
    return (await session.scalars(select(SkillGrant).order_by(SkillGrant.id))).all()


@router.post("/api/skill-grants", response_model=SkillGrantRead, status_code=201)
async def create_skill_grant(payload: SkillGrantCreate, session: SessionDep):
    if registry.get(payload.skill) is None:
        raise HTTPException(status_code=404, detail="skill not found")
    grant = SkillGrant(**payload.model_dump())
    session.add(grant)
    await session.commit()
    await session.refresh(grant)
    return grant


@router.delete("/api/skill-grants/{grant_id}", status_code=204)
async def delete_skill_grant(grant_id: int, session: SessionDep):
    result = await session.execute(delete(SkillGrant).where(SkillGrant.id == grant_id))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="skill grant not found")
    await session.commit()


@router.get("/api/skills", response_model=list[SkillSummary])
async def list_skills():
    return [item.summary() for item in registry.list()]


@router.post("/api/executions", response_model=ExecRead)
async def execute(payload: ExecRequest, request: Request, session: SessionDep):
    try:
        client, session_id = await _request_principal(request, session)
        return await ExecutionService(session).submit(
            payload,
            client=client,
            session_id=session_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/executions/{execution_id}", response_model=ExecutionStatusRead)
async def execution(
    execution_id: str,
    session: SessionDep,
    after_sequence: int = Query(default=0, ge=0),
):
    result = await ExecutionService(session).status(
        execution_id,
        after_sequence=after_sequence,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return result


@router.get("/api/approvals", response_model=list[ApprovalRead])
async def approvals(session: SessionDep):
    return (
        await session.scalars(select(Approval).order_by(Approval.created_at.desc()))
    ).all()


@router.post("/api/approvals/{execution_id}/approve", response_model=ExecRead)
async def approve(
    execution_id: str,
    session: SessionDep,
    always_allow: bool = False,
    wait: bool = True,
):
    try:
        return await ExecutionService(session).approve(
            execution_id,
            always_allow=always_allow,
            wait=wait,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/approvals/{execution_id}/deny", response_model=ExecRead)
async def deny(execution_id: str, session: SessionDep):
    try:
        return await ExecutionService(session).deny(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/audit", response_model=list[AuditEventRead])
async def audit(session: SessionDep, limit: int = Query(default=200, ge=1, le=1000)):
    return (
        await session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
        )
    ).all()
