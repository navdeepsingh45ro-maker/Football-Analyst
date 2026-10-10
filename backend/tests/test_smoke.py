"""The foundation: the app starts, reaches its database, and fails safely."""
from fastapi.testclient import TestClient
from sqlalchemy import text

import routes.meta_routes as meta_routes
from main import app


def test_health_reports_database_and_schema(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["schema_is_current"] is True


def test_foreign_keys_are_switched_on(db):
    # SQLite ignores foreign keys unless each connection enables them (database.py).
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_vocabulary_lists_are_served(client):
    body = client.get("/api/meta/vocabulary").json()
    assert "Diagonal run" in body["movement_categories"]
    assert "Off-ball movement" in body["observation_categories"]
    assert body["pitch"] == {"length_m": 105.0, "width_m": 68.0, "margin_m": 5.0}
    assert body["annotation_kinds"]["angle"] == {"min_points": 3, "max_points": 3}
    assert body["rating_scale"]["1"] == "Clear weakness"


def test_frontend_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Football Analyst" in response.text


def test_unknown_api_address_answers_with_json(client):
    response = client.get("/api/no-such-thing")
    assert response.status_code == 404
    assert "no API endpoint" in response.json()["detail"]


def test_security_headers_are_set(client):
    api = client.get("/api/health")
    assert api.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in api.headers["content-security-policy"]
    assert api.headers["cache-control"] == "no-store"
    page = client.get("/")
    assert page.headers["cache-control"] == "no-cache"


def test_requests_addressed_to_another_host_are_refused(client):
    response = client.get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 400


def test_unexpected_errors_never_leak_details(monkeypatch):
    def explode():
        raise RuntimeError("secret internal detail /Users/someone/private")

    monkeypatch.setattr(meta_routes, "current_revision", explode)
    # raise_server_exceptions=False: see the response a browser would get.
    response = TestClient(app, raise_server_exceptions=False).get("/api/health")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert "nothing was saved" in response.json()["detail"]
