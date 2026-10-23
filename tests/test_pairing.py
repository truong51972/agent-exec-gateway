from pathlib import Path

import asyncssh

from agent_exec_gateway.hosts import ensure_keypair


def test_pairing_key_is_reused(tmp_path: Path):
    path = tmp_path / "gateway.ed25519"
    first = ensure_keypair(path)
    second = ensure_keypair(path)

    assert first == second
    assert path.exists()
    parsed = asyncssh.read_private_key(str(path))
    exported = parsed.export_public_key("openssh")
    text = exported.decode() if isinstance(exported, bytes) else str(exported)
    assert first == text.strip()
