#!/usr/bin/env python3
"""Encrypt/decrypt a model directory using AES-256-GCM without disk plaintext archives."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHUNK_SIZE = 8 * 1024 * 1024
FORMAT = "cc-vllm-demo/aes-256-gcm/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def read_dek(path: Path) -> bytes:
    raw = path.read_bytes().strip()
    try:
        key = bytes.fromhex(raw.decode())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("DEK must be a hexadecimal 256-bit key") from exc
    if len(key) != 32:
        raise ValueError("DEK must be exactly 32 bytes (256-bit)")
    return key


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(data)


def encrypt_directory(source_dir: Path, ciphertext: Path, metadata: Path, dek_out: Path) -> None:
    if not source_dir.is_dir():
        raise ValueError(f"not a directory: {source_dir}")
    if ciphertext.exists() or metadata.exists() or dek_out.exists():
        raise ValueError("refusing to overwrite output, metadata, or DEK")
    tmpfs = Path(os.environ.get("CC_DEMO_TMPFS", "/dev/shm"))
    if not os.access(tmpfs, os.W_OK):
        raise ValueError(f"tmpfs is not writable: {tmpfs}")
    dek, nonce = os.urandom(32), os.urandom(12)
    ciphertext.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=tmpfs, suffix=".tar", delete=False) as plain:
        plain_path = Path(plain.name)
    try:
        with tarfile.open(plain_path, "w") as archive:
            archive.add(source_dir, arcname="model", recursive=True)
        encryptor = Cipher(algorithms.AES(dek), modes.GCM(nonce)).encryptor()
        with plain_path.open("rb") as source, ciphertext.open("xb") as target:
            for block in iter(lambda: source.read(CHUNK_SIZE), b""):
                target.write(encryptor.update(block))
            target.write(encryptor.finalize())
        record = {
            "format": FORMAT,
            "algorithm": "AES-256-GCM",
            "nonce_b64": base64.b64encode(nonce).decode(),
            "tag_b64": base64.b64encode(encryptor.tag).decode(),
            "ciphertext_sha256": sha256_file(ciphertext),
        }
        metadata.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        write_private(dek_out, dek.hex().encode() + b"\n")
    except Exception:
        ciphertext.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        raise
    finally:
        plain_path.unlink(missing_ok=True)


def decrypt_directory(ciphertext: Path, metadata: Path, dek_file: Path, destination: Path) -> None:
    record = json.loads(metadata.read_text(encoding="utf-8"))
    if record.get("format") != FORMAT or record.get("algorithm") != "AES-256-GCM":
        raise ValueError("unsupported encrypted-model format")
    if sha256_file(ciphertext) != record.get("ciphertext_sha256"):
        raise ValueError("ciphertext SHA-256 mismatch")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    if not str(destination.resolve()).startswith("/dev/shm/"):
        raise ValueError("refusing to decrypt outside tmpfs (/dev/shm)")
    decrypted_tar = destination / ".model.tar"
    try:
        decryptor = Cipher(
            algorithms.AES(read_dek(dek_file)),
            modes.GCM(base64.b64decode(record["nonce_b64"]), base64.b64decode(record["tag_b64"])),
        ).decryptor()
        with ciphertext.open("rb") as source, decrypted_tar.open("xb") as target:
            for block in iter(lambda: source.read(CHUNK_SIZE), b""):
                target.write(decryptor.update(block))
            target.write(decryptor.finalize())
        with tarfile.open(decrypted_tar, "r") as archive:
            for member in archive.getmembers():
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise ValueError("unsafe path in model archive")
            archive.extractall(destination, filter="data")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        decrypted_tar.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    encrypt = commands.add_parser("encrypt")
    encrypt.add_argument("--source", type=Path, required=True)
    encrypt.add_argument("--ciphertext", type=Path, required=True)
    encrypt.add_argument("--metadata", type=Path, required=True)
    encrypt.add_argument("--dek-out", type=Path, required=True)
    decrypt = commands.add_parser("decrypt")
    decrypt.add_argument("--ciphertext", type=Path, required=True)
    decrypt.add_argument("--metadata", type=Path, required=True)
    decrypt.add_argument("--dek-file", type=Path, required=True)
    decrypt.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "encrypt":
        encrypt_directory(args.source, args.ciphertext, args.metadata, args.dek_out)
    else:
        decrypt_directory(args.ciphertext, args.metadata, args.dek_file, args.destination)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"model_crypto: {exc}", file=sys.stderr)
        raise SystemExit(1)
