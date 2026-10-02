from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Host, HostCapability, SkillGrant
from .schemas import HostCapabilityRead, SkillPermission, SkillSummary


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    requires_commands: list[str]
    permissions: list[SkillPermission]
    instructions: str

    def matches(self, argv: list[str]) -> bool:
        if not argv:
            return False
        for permission in self.permissions:
            if permission.command != argv[0]:
                continue
            if permission.args_prefix and (
                argv[1 : 1 + len(permission.args_prefix)] != permission.args_prefix
            ):
                continue
            return True
        return False

    def summary(self) -> SkillSummary:
        return SkillSummary(
            name=self.name,
            description=self.description,
            requires_commands=self.requires_commands,
            permissions=self.permissions,
        )


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).parent / "skills"

    def list(self) -> list[SkillDefinition]:
        items: list[SkillDefinition] = []
        if not self.root.exists():
            return items
        for directory in sorted(path for path in self.root.iterdir() if path.is_dir()):
            metadata_path = directory / "metadata.yaml"
            instructions_path = directory / "SKILL.md"
            if not metadata_path.exists() or not instructions_path.exists():
                continue
            metadata = yaml.safe_load(metadata_path.read_text()) or {}
            requires = metadata.get("requires", {}) or {}
            permissions = [
                SkillPermission.model_validate(item)
                for item in metadata.get("permissions", [])
            ]
            items.append(
                SkillDefinition(
                    name=metadata["name"],
                    description=metadata.get("description", ""),
                    requires_commands=list(requires.get("commands", [])),
                    permissions=permissions,
                    instructions=instructions_path.read_text(),
                )
            )
        return items

    def get(self, name: str) -> SkillDefinition | None:
        return next((item for item in self.list() if item.name == name), None)

    def render_index(self) -> str:
        lines = ["# Agent Exec Gateway Skills", ""]
        for skill in self.list():
            commands = ", ".join(skill.requires_commands) or "none"
            lines.append(f"- **{skill.name}** — {skill.description} (requires: {commands})")
        return "\n".join(lines)


registry = SkillRegistry()


class SkillGrantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[SkillGrant]:
        return list(
            (
                await self.session.scalars(
                    select(SkillGrant).order_by(
                        SkillGrant.client, SkillGrant.host, SkillGrant.skill
                    )
                )
            ).all()
        )

    async def delete(self, grant_id: int) -> bool:
        result = await self.session.execute(
            delete(SkillGrant).where(SkillGrant.id == grant_id)
        )
        await self.session.commit()
        return bool(result.rowcount)


class CapabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def cached(self, host_name: str) -> list[HostCapabilityRead]:
        rows = (
            await self.session.scalars(
                select(HostCapability)
                .where(HostCapability.host_name == host_name)
                .order_by(HostCapability.skill)
            )
        ).all()
        return [HostCapabilityRead.model_validate(item) for item in rows]

    async def replace(
        self,
        host: Host,
        results: list[tuple[str, bool, dict]],
    ) -> list[HostCapabilityRead]:
        await self.session.execute(
            delete(HostCapability).where(HostCapability.host_name == host.name)
        )
        rows = [
            HostCapability(
                host_name=host.name,
                skill=skill,
                available=available,
                details=details,
            )
            for skill, available, details in results
        ]
        self.session.add_all(rows)
        await self.session.commit()
        for row in rows:
            await self.session.refresh(row)
        return [HostCapabilityRead.model_validate(item) for item in rows]
