"""API tests: required run note, server-side note filter, auditor read-only.

Uses an in-memory SQLite database via dependency override; the background
pipeline is pointed at the same test database by patching app.api.SessionLocal.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api_module
from app.database import Base, get_db
from app.main import app


GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
# Background pipeline task must write to the same test database.
api_module.SessionLocal = TestingSessionLocal

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def auth_header(username: str, password: str) -> dict:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def bioops_headers():
    return auth_header("bioops", "fastq123456")


@pytest.fixture
def auditor_headers():
    return auth_header("auditor", "audit123456")


def create_job(headers, note, fastq=GOOD_FASTQ):
    return client.post("/api/jobs", json={"fastqText": fastq, "note": note}, headers=headers)


@pytest.mark.parametrize("payload", [
    {"fastqText": GOOD_FASTQ},                      # 缺失备注
    {"fastqText": GOOD_FASTQ, "note": ""},          # 空备注
    {"fastqText": GOOD_FASTQ, "note": "   "},       # 纯空白备注
])
def test_blank_note_rejected(bioops_headers, payload):
    res = client.post("/api/jobs", json=payload, headers=bioops_headers)
    assert res.status_code == 422, res.text
    # 没有作业落库
    jobs = client.get("/api/jobs", headers=bioops_headers).json()
    assert jobs == []


def test_create_job_stores_note(bioops_headers):
    res = create_job(bioops_headers, "  Alpha批次 复检  ")
    assert res.status_code == 201, res.text
    job_id = res.json()["id"]
    assert res.json()["note"] == "Alpha批次 复检"  # 首尾空白被裁剪

    detail = client.get(f"/api/jobs/{job_id}", headers=bioops_headers).json()
    assert detail["note"] == "Alpha批次 复检"

    listed = client.get("/api/jobs", headers=bioops_headers).json()
    assert [j["note"] for j in listed] == ["Alpha批次 复检"]


def test_note_keyword_filter(bioops_headers):
    create_job(bioops_headers, "Alpha批次 复检")
    create_job(bioops_headers, "日常巡检")

    all_jobs = client.get("/api/jobs", headers=bioops_headers).json()
    assert len(all_jobs) == 2

    filtered = client.get("/api/jobs", params={"note": "复检"}, headers=bioops_headers).json()
    assert len(filtered) == 1
    assert filtered[0]["note"] == "Alpha批次 复检"

    other = client.get("/api/jobs", params={"note": "巡检"}, headers=bioops_headers).json()
    assert len(other) == 1
    assert other[0]["note"] == "日常巡检"

    none = client.get("/api/jobs", params={"note": "不存在的关键词"}, headers=bioops_headers).json()
    assert none == []

    # 空白关键词不过滤
    blank = client.get("/api/jobs", params={"note": "  "}, headers=bioops_headers).json()
    assert len(blank) == 2


def test_auditor_read_only(bioops_headers, auditor_headers):
    # 审计员不能开跑
    res = create_job(auditor_headers, "审计员尝试开跑")
    assert res.status_code == 403, res.text

    # 但看得见历史与详情
    job_id = create_job(bioops_headers, "运维正常开跑").json()["id"]
    listed = client.get("/api/jobs", headers=auditor_headers)
    assert listed.status_code == 200
    assert [j["id"] for j in listed.json()] == [job_id]
    detail = client.get(f"/api/jobs/{job_id}", headers=auditor_headers)
    assert detail.status_code == 200
    assert detail.json()["note"] == "运维正常开跑"
