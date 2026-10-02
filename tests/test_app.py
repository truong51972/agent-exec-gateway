import sys

from fastapi.testclient import TestClient

from agent_exec_gateway.app import app


def test_health_and_approval_execution_flow():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        submitted = client.post(
            "/api/executions",
            json={
                "host": "local",
                "argv": [sys.executable, "-c", "print('hello from gateway')"],
            },
        )
        assert submitted.status_code == 200
        execution = submitted.json()
        assert execution["decision"] == "ask"
        assert execution["status"] == "awaiting_approval"

        approved = client.post(f"/api/approvals/{execution['id']}/approve")
        assert approved.status_code == 200
        result = approved.json()
        assert result["status"] == "completed"
        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "hello from gateway"
