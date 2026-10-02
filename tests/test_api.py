import csv
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app, demos, uploads, lock
from app.touchstone import MAX_BYTES
from .test_touchstone import fixture


@pytest.fixture
def client():
    with lock:
        uploads.clear()
    with TestClient(app) as c:
        yield c


def test_demo_report_and_all_point_csv(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    demo = client.get("/api/demo").json()
    body = {
        "dataset_ids": [d["id"] for d in demo["datasets"]],
        "requirements": demo["requirements"],
    }
    response = client.post("/api/analyze", json=body)
    assert response.status_code == 200
    result = response.json()
    assert [d["verdict"] for d in result["datasets"]] == ["PASS", "FAIL"]
    assert all(d["source"] == "synthetic" for d in result["datasets"])
    report = client.post("/api/report", json=body)
    assert (
        report.status_code == 200
        and "<svg" in report.text
        and "SYNTHETIC" in report.text
    )
    assert "filter-degraded.s2p" in report.text and "STOP-H" in report.text
    rows = list(csv.reader(io.StringIO(client.get("/api/datasets/nominal/csv").text)))
    assert len(rows) == 1202 and len(rows[0]) == 9
    assert float(rows[1][0]) == 1.9e9
    assert client.get("/api/examples/nominal").content.startswith(b"! SYNTHETIC")


def test_upload_reference_mismatch_and_safe_report_names(client):
    raw, _ = fixture()
    response = client.post(
        "/api/upload",
        params={"filename": "../<script>alert(1)</script>.s2p"},
        content=raw,
    )
    assert response.status_code == 201
    n = response.json()
    assert n["source"] == "uploaded"
    body = {"dataset_ids": [n["id"]]}
    assert (
        client.post("/api/analyze", json=body).json()["datasets"][0]["verdict"]
        == "INCOMPLETE"
    )
    text = client.post("/api/report", json=body).text
    assert "<script>" not in text
    other, _ = fixture(reference=75)
    n2 = client.post(
        "/api/upload", params={"filename": "other.s2p"}, content=other
    ).json()
    assert (
        client.post(
            "/api/analyze", json={"dataset_ids": [n["id"], n2["id"]]}
        ).status_code
        == 422
    )


def test_missing_files_bad_request_and_body_limit(client):
    assert (
        client.post("/api/analyze", json={"dataset_ids": ["missing"]}).status_code
        == 404
    )
    assert client.post("/api/analyze", json={"dataset_ids": []}).status_code == 422
    assert (
        client.post("/api/analyze", json={"dataset_ids": ["nominal"] * 3}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/upload", params={"filename": "bad.s2p"}, content=b"invalid"
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/upload",
            params={"filename": "big.s2p"},
            content=b"!" * (MAX_BYTES + 1),
        ).status_code
        == 413
    )
    assert client.get("/api/examples/unknown").status_code == 404


def test_uploaded_demo_is_recognized_by_content_not_filename(client):
    raw = client.get("/api/examples/nominal").content
    n = client.post(
        "/api/upload", params={"filename": "renamed.s2p"}, content=raw
    ).json()
    assert n["source"] == "synthetic"
    raw, _ = fixture()
    n = client.post(
        "/api/upload", params={"filename": "filter-nominal.s2p"}, content=raw
    ).json()
    assert n["source"] == "uploaded"


def test_upload_memory_limit_evicts_oldest(client):
    raw, _ = fixture()
    ids = [
        client.post(
            "/api/upload", params={"filename": f"test-{i}.s2p"}, content=raw
        ).json()["id"]
        for i in range(33)
    ]
    assert (
        client.post("/api/analyze", json={"dataset_ids": [ids[0]]}).status_code == 404
    )
    assert (
        client.post("/api/analyze", json={"dataset_ids": [ids[-1]]}).status_code == 200
    )


def test_nonfinite_requirement_returns_clean_validation_error(client):
    response = client.post(
        "/api/analyze",
        content='{"dataset_ids":["nominal"],"requirements":{"max_loss_db":Infinity}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "finite_number"
