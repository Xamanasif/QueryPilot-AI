import pytest
from fastapi.testclient import TestClient

from querypilot.api import create_app
from querypilot.config import Settings
from querypilot.db import Database

ACME_ANALYST = {"X-API-Key": "qp_acme_analyst_demo"}
ACME_REVIEWER = {"X-API-Key": "qp_acme_reviewer_demo"}
GLOBEX_ANALYST = {"X-API-Key": "qp_globex_analyst_demo"}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "querypilot.db"), groq_api_key=None)


@pytest.fixture
def db(settings) -> Database:
    database = Database(settings.db_path)
    database.seed_demo()
    return database


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
