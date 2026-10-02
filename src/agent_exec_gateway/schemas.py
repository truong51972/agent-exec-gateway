from datetime import datetime

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


class HostRead(HostCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool
    created_at: datetime


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


class ExecRequest(BaseModel):
    host: str = "local"
    argv: list[str] = Field(min_length=1)
    cwd: str | None = None

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


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_id: str
    status: str
    created_at: datetime
    decided_at: datetime | None
