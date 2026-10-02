from agent_exec_gateway.schemas import SkillPermission
from agent_exec_gateway.skills import registry


def test_builtin_skills_are_loadable_and_enforce_declared_commands():
    browser = registry.get("browserskill")
    assert browser is not None
    assert "bsk" in browser.requires_commands
    assert browser.matches(["bsk", "snapshot", "--json"])
    assert not browser.matches(["git", "status"])

    filesystem = registry.get("filesystem")
    assert filesystem is not None
    assert filesystem.matches(["@file.read", "/tmp/a"])
    assert filesystem.matches(["@file.write", "/tmp/a"])


def test_skill_permission_prefix_matching():
    git_read = registry.get("git-read")
    assert git_read is not None
    assert SkillPermission(command="git", args_prefix=["status"]) in git_read.permissions
    assert git_read.matches(["git", "status", "--short"])
    assert not git_read.matches(["git", "push"])
