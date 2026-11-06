"""API + worker de extremo a extremo con el traductor falso."""
import os

import pytest

from .conftest import OUT


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["FAKE_TRANSLATOR"] = "true"
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.cli import migrate

    migrate()
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_upload_validations(client, sample_pdf):
    r = client.post("/api/jobs", files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
                    data={"rights_confirmed": "true"})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    r = client.post("/api/jobs", files={"file": ("x.pdf", sample_pdf.read_bytes(), "application/pdf")},
                    data={"rights_confirmed": "false"})
    assert r.status_code == 400


def test_upload_process_download(client, sample_pdf):
    from app import worker

    r = client.post("/api/jobs", files={"file": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
                    data={"rights_confirmed": "true"})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    assert r.json()["status"] == "queued"

    claimed = worker.claim_job()
    assert claimed == job_id
    worker.process(job_id)

    st = client.get(f"/api/jobs/{job_id}").json()
    assert st["status"] == "done", st
    assert st["progress"] == 100
    assert all(s["state"] == "completed" for s in st["stages"])
    assert st["output_name"].endswith("(ES).pdf")

    pdf = client.get(f"/api/jobs/{job_id}/download")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    rep = client.get(f"/api/jobs/{job_id}/report").json()
    assert rep["validaciones"]["mismo_numero_de_paginas"]
    img = client.get(f"/api/jobs/{job_id}/pages/1/preview?version=original")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    (OUT / "api_download.pdf").write_bytes(pdf.content)
