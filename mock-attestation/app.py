from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from l1_demo.assertion import sign_assertion

app = FastAPI(title="L1 demo-mock attestation", docs_url=None, redoc_url=None)
KEY = Path(os.environ.get("MOCK_SIGNING_KEY_FILE", "/run/secrets/mock-signing.key"))


class AssertionRequest(BaseModel):
    nonce: str
    image_digest: str
    model_ciphertext_sha256: str
    inference_config_sha256: str
    policy_version: str


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live", "environment": "demo-mock"}


@app.post("/v1/assertions")
def issue_assertion(request: AssertionRequest) -> dict[str, str]:
    if not KEY.is_file():
        raise HTTPException(503, "mock signing key unavailable")
    now = int(time.time())
    claims = request.model_dump() | {
        "environment": "demo-mock",
        "issued_at": now,
        "expires_at": now + int(os.getenv("ASSERTION_TTL_SECONDS", "60")),
    }
    return {"assertion": sign_assertion(claims, KEY.read_bytes().strip())}
