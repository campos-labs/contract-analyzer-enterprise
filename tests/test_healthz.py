from http import HTTPStatus

from fastapi.testclient import TestClient

from contract_analyzer_enterprise.app import app


def test_healthz_returns_ok(monkeypatch):
    monkeypatch.delenv('APP_LOG_LEVEL', raising=False)
    with TestClient(app) as client:
        response = client.get('/healthz')

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'status': 'ok'}
