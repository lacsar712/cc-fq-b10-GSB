"""API tests: remark required on submit, server-side remark filter, auditor role."""

GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""


def _create_job(client, headers, remark, fastq_text=GOOD_FASTQ):
    return client.post(
        "/api/jobs",
        json={"fastqText": fastq_text, "remark": remark},
        headers=headers,
    )


def test_empty_remark_rejected(client, bioops_headers):
    resp = _create_job(client, bioops_headers, remark="")
    assert resp.status_code == 400
    assert "备注" in resp.json()["detail"]


def test_blank_remark_rejected(client, bioops_headers):
    resp = _create_job(client, bioops_headers, remark="   \n\t ")
    assert resp.status_code == 400
    assert "备注" in resp.json()["detail"]


def test_missing_remark_rejected(client, bioops_headers):
    resp = client.post(
        "/api/jobs",
        json={"fastqText": GOOD_FASTQ},
        headers=bioops_headers,
    )
    assert resp.status_code == 422


def test_remark_persisted_and_visible_in_detail(client, bioops_headers):
    remark = "肿瘤panel批次A-tumor-batch-001"
    resp = _create_job(client, bioops_headers, remark=remark)
    assert resp.status_code == 201
    job_id = resp.json()["id"]
    assert resp.json()["remark"] == remark

    detail = client.get(f"/api/jobs/{job_id}", headers=bioops_headers)
    assert detail.status_code == 200
    assert detail.json()["remark"] == remark


def test_remark_keyword_server_side_filter(client, bioops_headers):
    r1 = _create_job(client, bioops_headers, remark="tumor-panel-20260921 批次甲")
    r2 = _create_job(client, bioops_headers, remark="germline-exome-20260921 批次乙")
    assert r1.status_code == 201 and r2.status_code == 201

    # 无关键字:两条都在
    all_jobs = client.get("/api/jobs", headers=bioops_headers).json()
    assert len(all_jobs) == 2

    # 按备注词过滤:只剩匹配的那一条
    filtered = client.get("/api/jobs", params={"remark": "tumor-panel"}, headers=bioops_headers)
    assert filtered.status_code == 200
    rows = filtered.json()
    assert len(rows) == 1
    assert "tumor-panel" in rows[0]["remark"]
    assert rows[0]["id"] == r1.json()["id"]

    # 纯空白关键字视为不过滤
    blank = client.get("/api/jobs", params={"remark": "   "}, headers=bioops_headers).json()
    assert len(blank) == 2

    # 无匹配关键字:空列表
    none_match = client.get(
        "/api/jobs", params={"remark": "no-such-keyword"}, headers=bioops_headers
    ).json()
    assert none_match == []


def test_auditor_can_view_but_cannot_submit(client, bioops_headers, auditor_headers):
    created = _create_job(client, bioops_headers, remark="audit-visible-remark")
    assert created.status_code == 201

    # 审计员看得见历史(含备注)与详情
    hist = client.get("/api/jobs", headers=auditor_headers)
    assert hist.status_code == 200
    assert len(hist.json()) == 1
    assert hist.json()[0]["remark"] == "audit-visible-remark"

    filtered = client.get(
        "/api/jobs", params={"remark": "audit-visible"}, headers=auditor_headers
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    detail = client.get(f"/api/jobs/{created.json()['id']}", headers=auditor_headers)
    assert detail.status_code == 200

    # 审计员不能开跑
    forbidden = _create_job(client, auditor_headers, remark="auditor-tried-to-run")
    assert forbidden.status_code == 403
