from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from l1_demo.assertion import AssertionError, sign_assertion, verify_assertion

ROOT = Path(__file__).resolve().parents[1]
CRYPTO = ROOT / "model-encryption" / "model_crypto.py"


class L1PrimitiveTests(unittest.TestCase):
    def test_assertion_expiry_and_signature(self) -> None:
        claims = {"environment": "demo-mock", "issued_at": 100, "expires_at": 200, "nonce": "one"}
        token = sign_assertion(claims, b"k" * 32)
        self.assertEqual(verify_assertion(token, b"k" * 32, now=150)["nonce"], "one")
        with self.assertRaises(AssertionError):
            verify_assertion(token, b"wrong" * 8, now=150)
        with self.assertRaises(AssertionError):
            verify_assertion(token, b"k" * 32, now=200)

    def test_encrypt_decrypt_and_tamper_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "config.json").write_text('{"demo": true}\n')
            cipher, metadata, dek = root / "model.gcm", root / "model.gcm.json", root / "dek.hex"
            subprocess.run([".venv/bin/python", str(CRYPTO), "encrypt", "--source", str(source), "--ciphertext", str(cipher), "--metadata", str(metadata), "--dek-out", str(dek)], cwd=ROOT, check=True)
            destination = Path("/dev/shm") / f"cc-vllm-test-{root.name}"
            subprocess.run([".venv/bin/python", str(CRYPTO), "decrypt", "--ciphertext", str(cipher), "--metadata", str(metadata), "--dek-file", str(dek), "--destination", str(destination)], cwd=ROOT, check=True)
            self.assertEqual((destination / "model" / "config.json").read_text(), '{"demo": true}\n')
            shutil.rmtree(destination)
            cipher.write_bytes(cipher.read_bytes() + b"x")
            failed = subprocess.run([".venv/bin/python", str(CRYPTO), "decrypt", "--ciphertext", str(cipher), "--metadata", str(metadata), "--dek-file", str(dek), "--destination", str(destination)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("ciphertext SHA-256 mismatch", failed.stderr)


if __name__ == "__main__":
    unittest.main()
