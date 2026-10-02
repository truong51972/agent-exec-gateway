from pathlib import Path

from fastapi.testclient import TestClient

from agent_exec_gateway.app import app


def test_file_operations_use_normal_policy_and_approval_flow(tmp_path: Path):
    target = tmp_path / "hello.txt"

    with TestClient(app) as client:
        submitted = client.post(
            "/api/executions",
            json={
                "host": "local",
                "argv": ["@file.write", str(target)],
                "skill": "filesystem",
                "payload": {"content": "hello from AEG"},
            },
        )
        assert submitted.status_code == 200
        execution = submitted.json()
        assert execution["status"] == "awaiting_approval"

        approved = client.post(f"/api/approvals/{execution['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert target.read_text() == "hello from AEG"

        read_request = client.post(
            "/api/executions",
            json={
                "host": "local",
                "argv": ["@file.read", str(target)],
                "skill": "filesystem",
            },
        )
        read_execution = read_request.json()
        read_result = client.post(
            f"/api/approvals/{read_execution['id']}/approve"
        ).json()
        assert read_result["stdout"] == "hello from AEG"
