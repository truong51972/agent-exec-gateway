from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Policy


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    policy_id: int | None = None


class PolicyEngine:
    def __init__(self, session: AsyncSession, *, default_decision: str = "ask") -> None:
        self.session = session
        self.default_decision = default_decision

    async def evaluate(self, *, client: str, host: str, argv: list[str]) -> PolicyDecision:
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
            return PolicyDecision(self.default_decision)

        _, best_rule = max(candidates, key=lambda item: item[0])
        return PolicyDecision(best_rule.decision, best_rule.id)
