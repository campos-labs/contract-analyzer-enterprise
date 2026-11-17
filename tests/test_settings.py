import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from contract_analyzer_enterprise.app import app
from contract_analyzer_enterprise.settings import Settings


def test_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv('APP_LOG_LEVEL', raising=False)

    settings = Settings()

    assert settings.log_level == 'INFO'


def test_log_level_accepts_debug(monkeypatch):
    monkeypatch.setenv('APP_LOG_LEVEL', 'DEBUG')

    with TestClient(app):
        assert app.state.settings.log_level == 'DEBUG'
        logger = logging.getLogger('contract_analyzer_enterprise')
        assert logger.level == logging.DEBUG


def test_invalid_log_level_prevents_startup(monkeypatch):
    monkeypatch.setenv('APP_LOG_LEVEL', 'INVALID')

    with pytest.raises(ValidationError):
        with TestClient(app):
            pass
