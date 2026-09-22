"""API test fixtures: in-memory SQLite + TestClient with overridden DB sessions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module
from app import main as main_module
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSession()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Background runner (_run_job_background) opens its own session
    original_session_local = api_module.SessionLocal
    # lifespan create_all/ensure_columns must target the test engine too
    original_engine = main_module.engine
    api_module.SessionLocal = TestingSession
    main_module.engine = engine
    try:
        yield session
    finally:
        main_module.engine = original_engine
        api_module.SessionLocal = original_session_local
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture()
def bioops_headers(client):
    token = _login(client, "bioops", "fastq123456")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auditor_headers(client):
    token = _login(client, "auditor", "audit123456")
    return {"Authorization": f"Bearer {token}"}
