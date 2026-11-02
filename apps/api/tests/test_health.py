from fastapi.testclient import TestClient

from polymech_api.main import app


def test_health_reports_version() -> None:
    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.1.0"}
