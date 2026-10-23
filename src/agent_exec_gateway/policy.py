from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Policy, SkillGrant
from .skills import registry


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    source: str = "default"
    reference: str | None = None

    @property
    def policy_id(self) -> int | None:
        if self.source != "command_policy" or self.reference is None:
            return None
        return int(self.reference)


class PolicyEngine:
    def __init__(self, session: AsyncSession, *, default_decision: str = "ask") -> None:
        self.session = session
        self.default_decision = default_decision

    async def evaluate(
        self,
        *,
        client: str,
        host: str,
        argv: list[str],
        skill: str | None = None,
    ) -> PolicyDecision:
        command_decision = await self._command_decision(
            client=client,
            host=host,
            argv=argv,
        )

        if skill is None:
            return command_decision or PolicyDecision(self.default_decision)

        definition = registry.get(skill)
        if definition is None:
            return PolicyDecision("deny", source="skill", reference=f"unknown:{skill}")
        if not definition.matches(argv):
            return PolicyDecision(
                "deny",
                source="skill",
                reference=f"outside-skill:{skill}",
            )

        if command_decision is not None:
            return command_decision

        grant = await self._skill_grant(client=client, host=host, skill=skill)
        if grant is not None:
            return PolicyDecision(
                grant.decision,
                source="skill_grant",
                reference=str(grant.id),
            )

        return PolicyDecision(self.default_decision, source="skill", reference=skill)

    async def _command_decision(
        self,
        *,
        client: str,
        host: str,
        argv: list[str],
    ) -> PolicyDecision | None:
        command = argv[0]
        rules = (await self.session.scalars(select(Policy))).all()
        candidates: list[tuple[tuple[int, int, int, int], Policy]] = []

        for rule in rules:
            if rule.client not in ("*", client):
                continue
            if rule.host not in ("*", host):
                continue
            if rule.command not in ("*", command):
                continue
            if rule.args_prefix and argv[1 : 1 + len(rule.args_prefix)] != rule.args_prefix:
                continue

            specificity = (
                int(rule.client != "*"),
                int(rule.host != "*"),
                int(rule.command != "*"),
                len(rule.args_prefix),
            )
            candidates.append((specificity, rule))

        if not candidates:
            return None

        _, best_rule = max(candidates, key=lambda item: item[0])
        return PolicyDecision(
            best_rule.decision,
            source="command_policy",
            reference=str(best_rule.id),
        )

    async def _skill_grant(
        self,
        *,
        client: str,
        host: str,
        skill: str,
    ) -> SkillGrant | None:
        grants = (
            await self.session.scalars(select(SkillGrant).where(SkillGrant.skill == skill))
        ).all()
        candidates: list[tuple[tuple[int, int], SkillGrant]] = []

        for grant in grants:
            if grant.client not in ("*", client):
                continue
            if grant.host not in ("*", host):
                continue
            specificity = (
                int(grant.client != "*"),
                int(grant.host != "*"),
            )
            candidates.append((specificity, grant))

        if not candidates:
            return None
        _, best = max(candidates, key=lambda item: item[0])
        return best
