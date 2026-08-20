#!/usr/bin/env python3
"""One-way local preparation after the model download has completed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model-encryption"))
from model_crypto import encrypt_directory, sha256_file  # noqa: E402


def private_write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True, help="downloaded model directory, outside this repository")
    parser.add_argument("--image-digest", required=True, help="resolved immutable inference-image digest (sha256:...)")
    parser.add_argument("--vllm-args", default="--max-model-len 2048 --gpu-memory-utilization 0.70")
    parser.add_argument("--policy-version", default="l1-demo-v1")
    args = parser.parse_args()
    if not args.image_digest.startswith("sha256:"):
        parser.error("--image-digest must be an immutable sha256: digest")
    encrypted, secrets_dir, config = ROOT / "encrypted-models", ROOT / "secrets", ROOT / "config"
    ciphertext, metadata, dek = encrypted / "model.tar.gcm", encrypted / "model.tar.gcm.json", secrets_dir / "demo-dek.hex"
    policy, env_file, signing_key = config / "policy.json", ROOT / ".env", secrets_dir / "mock-signing.key"
    existing = [path for path in (ciphertext, metadata, dek, policy, env_file, signing_key) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing L1 material: " + ", ".join(str(path) for path in existing))
    encrypt_directory(args.model_dir, ciphertext, metadata, dek)
    private_write_once(signing_key, secrets.token_bytes(32))
    cipher_hash = json.loads(metadata.read_text(encoding="utf-8"))["ciphertext_sha256"]
    config_hash = hashlib.sha256(args.vllm_args.encode()).hexdigest()
    policy.write_text(json.dumps({
        "environment": "demo-mock",
        "image_digest": args.image_digest,
        "inference_config_sha256": config_hash,
        "model_ciphertext_sha256": cipher_hash,
        "policy_version": args.policy_version,
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    env_file.write_text(
        "ATTESTATION_PROVIDER=mock\n"
        f"POLICY_VERSION={args.policy_version}\n"
        f"WORKLOAD_IMAGE_DIGEST={args.image_digest}\n"
        f"VLLM_ARGS={args.vllm_args}\n"
        "DEMO_PORT=8000\n",
        encoding="utf-8",
    )
    print(f"ciphertext_sha256={cipher_hash}")
    print("prepared L1 material; plaintext model source was intentionally retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
