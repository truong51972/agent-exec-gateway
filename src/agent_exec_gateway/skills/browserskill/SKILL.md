# BrowserSkill

Use BrowserSkill through Agent Exec Gateway with `skill="browserskill"`.

## Procedure

1. Inspect the current page with `bsk snapshot --json`.
2. Use element references from the newest snapshot.
3. Interact with `bsk click`, `bsk fill`, or other BrowserSkill commands.
4. Snapshot again after navigation or a meaningful UI change.
5. Never assume a UI action succeeded without verifying it.

## Human handoff

Stop and ask for human intervention for CAPTCHA, unexpected authentication prompts,
or any destructive action whose effect is not clear.
