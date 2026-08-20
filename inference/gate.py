"""Fail-closed L1 startup gate and a small reverse proxy for local vLLM."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import httpx
from fastapi import FastAPI, Request as FastAPIRequest, Response

from model_encryption.model_crypto import decrypt_directory, sha256_file

STATE: dict[str, Any] = {"ready": False, "reason": "startup_pending", "process": None}
RUNTIME = Path("/run/model")


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:  # nosec: internal Compose services only
        return json.loads(response.read())


def unlock() -> Path:
    if os.getenv("ATTESTATION_PROVIDER", "mock") != "mock":
        raise RuntimeError("trustee adapter is intentionally not implemented in L1")
    ciphertext = Path(os.environ["MODEL_CIPHERTEXT"])
    metadata = Path(os.environ["MODEL_METADATA"])
    config_hash = hashlib.sha256(os.getenv("VLLM_ARGS", "").encode()).hexdigest()
    challenge = post_json(f"{os.environ['KEY_BROKER_URL']}/v1/challenges", {})
    facts = {
        "nonce": challenge["nonce"],
        "image_digest": os.environ["WORKLOAD_IMAGE_DIGEST"],
        "model_ciphertext_sha256": sha256_file(ciphertext),
        "inference_config_sha256": config_hash,
        "policy_version": os.environ["POLICY_VERSION"],
    }
    assertion = post_json(f"{os.environ['MOCK_ATTESTATION_URL']}/v1/assertions", facts)["assertion"]
    dek = post_json(f"{os.environ['KEY_BROKER_URL']}/v1/deks", {"nonce": challenge["nonce"], "assertion": assertion})["dek_b64"]
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    dek_path = RUNTIME / "dek.hex"
    dek_path.write_text(base64.b64decode(dek).hex() + "\n", encoding="utf-8")
    dek_path.chmod(0o600)
    destination = RUNTIME / "model"
    decrypt_directory(ciphertext, metadata, dek_path, destination)
    dek_path.unlink(missing_ok=True)
    return destination / "model"


async def start_vllm() -> None:
    model_path = unlock()
    args = ["vllm", "serve", str(model_path), "--host", "127.0.0.1", "--port", "8001"]
    args.extend(os.getenv("VLLM_ARGS", "--max-model-len 2048").split())
    STATE["process"] = subprocess.Popen(args, env=os.environ.copy())
    async with httpx.AsyncClient() as client:
        for _ in range(90):
            if STATE["process"].poll() is not None:
                raise RuntimeError("vLLM exited during startup")
            try:
                if (await client.get("http://127.0.0.1:8001/health", timeout=1)).is_success:
                    STATE.update(ready=True, reason="ready")
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise RuntimeError("vLLM readiness timeout")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await start_vllm()
    except Exception as exc:
        STATE.update(ready=False, reason=type(exc).__name__)
    yield
    process = STATE.get("process")
    if process and process.poll() is None:
        process.terminate()
    shutil.rmtree(RUNTIME / "model", ignore_errors=True)


app = FastAPI(title="L1 inference gate", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/health/ready")
def ready() -> Response:
    return Response(status_code=200 if STATE["ready"] else 503, content=json.dumps({"status": STATE["reason"]}), media_type="application/json")


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: FastAPIRequest) -> Response:
    if not STATE["ready"]:
        return Response(status_code=503, content='{"error":"not_ready"}', media_type="application/json")
    async with httpx.AsyncClient() as client:
        upstream = await client.request(request.method, f"http://127.0.0.1:8001/v1/{path}", content=await request.body(), headers={k: v for k, v in request.headers.items() if k.lower() != "host"})
    return Response(upstream.content, status_code=upstream.status_code, headers={"content-type": upstream.headers.get("content-type", "application/json")})
