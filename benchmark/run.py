#!/usr/bin/env python3
"""Run the PLAN.md 1/4/8-concurrency baseline and retain non-sensitive raw timing data."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def percentile(values: list[float], p: int) -> float:
    return sorted(values)[max(0, min(len(values) - 1, round((len(values) - 1) * p / 100)))]


def request_once(url: str, model: str) -> dict[str, float | int]:
    # Fixed, non-sensitive test text. The prompt itself is intentionally omitted from result logs.
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "用一句话说明条件发钥。"}], "temperature": 0, "max_tokens": 128}).encode()
    started = time.perf_counter()
    try:
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:  # nosec: operator-provided benchmark URL
            payload = json.loads(response.read())
        elapsed = time.perf_counter() - started
        tokens = int(payload.get("usage", {}).get("completion_tokens", 0))
        return {"status": 200, "latency_seconds": elapsed, "completion_tokens": tokens}
    except Exception:
        return {"status": 0, "latency_seconds": time.perf_counter() - started, "completion_tokens": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.jsonl"))
    args = parser.parse_args()
    if args.requests < 30:
        parser.error("PLAN.md requires at least 30 requests per concurrency group")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, float | int]] = []
    with args.output.open("x", encoding="utf-8") as raw:
        for concurrency in (1, 4, 8):
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(executor.map(lambda _: request_once(args.url, args.model), range(args.requests)))
            for result in results:
                raw.write(json.dumps({"concurrency": concurrency} | result) + "\n")
            successful = [float(item["latency_seconds"]) for item in results if item["status"] == 200]
            summary.append({
                "concurrency": concurrency,
                "requests": len(results),
                "successes": len(successful),
                "errors": len(results) - len(successful),
                "latency_p50_seconds": percentile(successful, 50) if successful else -1,
                "latency_p95_seconds": percentile(successful, 95) if successful else -1,
            })
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
