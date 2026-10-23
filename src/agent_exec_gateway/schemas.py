from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    transport: str = Field(default="ssh", pattern="^(local|ssh)$")
    hostname: str | None = None
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = None
    identity_file: str | None = None

    @model_validator(mode="after")
    def validate_ssh_fields(self) -> "HostCreate":
        if self.transport == "ssh" and not self.hostname:
            raise ValueError("hostname is required for SSH hosts")
        return self


class HostUpdate(BaseModel):
    hostname: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    identity_file: str | None = None
    enabled: bool | None = None


class HostRead(HostCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool
    created_at: datetime


class PairingInfo(BaseModel):
    host: str
    identity_file: str
    public_key: str
    install_command: str


class HostTestResult(BaseModel):
    host: str
    ok: bool
    message: str


class PolicyCreate(BaseModel):
    client: str = "*"
    host: str = "*"
    command: str = "*"
    args_prefix: list[str] = Field(default_factory=list)
    decision: str = Field(pattern="^(allow|ask|deny)$")


class PolicyRead(PolicyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    enabled: bool
    created_at: datetime


class ClientCreated(ClientRead):
    token: str


class ClientUpdate(BaseModel):
    enabled: bool


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_name: str
    protocol: str
    external_id: str
    created_at: datetime
    last_seen_at: datetime


class SkillPermission(BaseModel):
    command: str
    args_prefix: list[str] = Field(default_factory=list)


class SkillSummary(BaseModel):
    name: str
    description: str
    requires_commands: list[str]
    permissions: list[SkillPermission]


class SkillGrantCreate(BaseModel):
    client: str = "*"
    host: str = "*"
    skill: str
    decision: str = Field(pattern="^(allow|ask|deny)$")


class SkillGrantRead(SkillGrantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class HostCapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host_name: str
    skill: str
    available: bool
    details: dict[str, Any]
    checked_at: datetime


class ExecRequest(BaseModel):
    host: str = "local"
    argv: list[str] = Field(min_length=1)
    cwd: str | None = None
    skill: str | None = None
    wait: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_empty_arguments(self) -> "ExecRequest":
        if any(not value for value in self.argv):
            raise ValueError("argv entries must not be empty")
        return self


class ExecRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client: str
    host_name: str
    cwd: str | None
    argv: list[str]
    decision: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    created_at: datetime
    completed_at: datetime | None


class ExecutionContextRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    session_id: str | None
    skill: str | None
    policy_source: str | None
    policy_ref: str | None


class ExecutionChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    stream: str
    data: str
    created_at: datetime


class ExecutionStatusRead(BaseModel):
    execution: ExecRead
    context: ExecutionContextRead | None = None
    chunks: list[ExecutionChunkRead] = Field(default_factory=list)
    next_sequence: int = 0


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_id: str
    status: str
    created_at: datetime
    decided_at: datetime | None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    actor: str
    host_name: str | None
    execution_id: str | None
    details: dict[str, Any]
    created_at: datetime
