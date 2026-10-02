"""Exercise the running server via real HTTP and save reproducible demo evidence."""

import argparse
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8003")
    parser.add_argument("--save-examples", action="store_true")
    options = parser.parse_args()
    with httpx.Client(base_url=options.url, timeout=15) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        demo = client.get("/api/demo").json()
        body = {
            "dataset_ids": [d["id"] for d in demo["datasets"]],
            "requirements": demo["requirements"],
        }
        response = client.post("/api/analyze", json=body)
        response.raise_for_status()
        result = response.json()
        assert [d["verdict"] for d in result["datasets"]] == ["PASS", "FAIL"]
        report = client.post("/api/report", json=body)
        report.raise_for_status()
        assert "<svg" in report.text and "SYNTHETIC" in report.text
        csv = client.get("/api/datasets/nominal/csv")
        csv.raise_for_status()
        assert len(csv.text.splitlines()) == 1202
        raw = client.get("/api/examples/nominal").content
        uploaded = client.post(
            "/api/upload", params={"filename": "upload-test.s2p"}, content=raw
        )
        uploaded.raise_for_status()
        assert uploaded.json()["source"] == "synthetic"
        assert (
            client.post(
                "/api/analyze", json={"dataset_ids": [uploaded.json()["id"]]}
            ).json()["datasets"][0]["verdict"]
            == "PASS"
        )
        lines = raw.decode().splitlines()
        partial = "\n".join(
            lines[:4]
            + [line for line in lines[4:] if 2.4 <= float(line.split()[0]) <= 2.5]
        )
        uploaded_partial = client.post(
            "/api/upload", params={"filename": "partial.s2p"}, content=partial.encode()
        )
        uploaded_partial.raise_for_status()
        incomplete = client.post(
            "/api/analyze", json={"dataset_ids": [uploaded_partial.json()["id"]]}
        ).json()["datasets"][0]
        assert incomplete["verdict"] == "INCOMPLETE"
        assert (
            client.post(
                "/api/upload", params={"filename": "bad.s2p"}, content=b"broken"
            ).status_code
            == 422
        )
        if options.save_examples:
            (ROOT / "examples/sample-report.html").write_text(report.text)
            (ROOT / "examples/sample-measurements.csv").write_bytes(csv.content)
            summary = {
                "url": options.url,
                "checks": [
                    "nominal PASS",
                    "degraded FAIL",
                    "upload round-trip",
                    "partial INCOMPLETE",
                    "malformed 422",
                    "standalone HTML and full-point CSV",
                ],
                "datasets": [
                    {
                        k: d[k]
                        for k in (
                            "name",
                            "source",
                            "sha256",
                            "verdict",
                            "points",
                            "checks",
                            "peak_frequency_ghz",
                            "bandwidth",
                        )
                    }
                    for d in result["datasets"]
                ],
            }
            (ROOT / "examples/live-results.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
            )
        print(
            "Live HTTP verified: nominal PASS; degraded FAIL; partial INCOMPLETE; upload; malformed input; HTML/CSV exports."
        )


if __name__ == "__main__":
    main()
