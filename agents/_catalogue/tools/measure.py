"""Measure this endpoint, rather than quoting somebody else's number.

One level per call, deliberately. A full sweep takes minutes and a chat request
does not wait that long — the first version of this tool ran the whole sweep
inside one call and the reader got "Could not reach the server". Splitting it
per level keeps every call short and, as a side effect, makes progress visible:
each level appears in the transcript as its own step with its own numbers.

Every latency figure in the catalogue is a median from another operator's
region, hardware and concurrency. None of it says what a user of *your* deploy
sees when eight of them arrive together — and that is the number that decides
whether an interactive product works. This runs the sweep and returns the curve.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import time

import httpx
from agentino import tool

# Hard caps. This is reachable from a public demo, so a sweep is bounded: at
# most 8 concurrent streams and a short completion each.
_DEFAULT_LEVELS = (1, 2, 4, 6, 8, 12, 16)
_MAX_CONCURRENCY = 16  # a public demo does not get to self-DDoS
_MAX_SAMPLES = 12
_MAX_TOKENS_CAP = 400
_MAX_TOKENS = 120
# One request at concurrency 1 is a sample, not a measurement — the first call
# also carries cold-start cost. Repeat each level until there are enough
# samples for a median that means something.
_MIN_SAMPLES = 5
_PROMPT = "List three causes of high tail latency in LLM serving. One line each."


async def _one(
    client: httpx.AsyncClient, url: str, key: str, model: str, max_tokens: int = _MAX_TOKENS
) -> dict:
    body = {
        "model": model,
        "stream": True,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": _PROMPT}],
    }
    t0 = time.perf_counter()
    ttft: float | None = None
    toks = 0
    try:
        async with client.stream(
            "POST", url, json=body, headers={"Authorization": f"Bearer {key}"}
        ) as r:
            if r.status_code != 200:
                return {"ok": False}
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = (json.loads(payload).get("choices") or [{}])[0].get("delta") or {}
                except Exception:
                    continue
                if delta.get("content"):
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    toks += 1
    except Exception:
        return {"ok": False}
    if ttft is None:
        return {"ok": False}
    total = time.perf_counter() - t0
    return {"ok": True, "ttft": ttft, "toks": toks, "tps": toks / max(total - ttft, 1e-6)}


def _parse_levels(spec: str) -> tuple[int, ...]:
    try:
        got = tuple(
            sorted({max(1, min(_MAX_CONCURRENCY, int(x))) for x in spec.split(",") if x.strip()})
        )
    except ValueError:
        return _DEFAULT_LEVELS
    return got or _DEFAULT_LEVELS


def _endpoint(model: str) -> tuple[str, str, str, str]:
    url = (os.environ.get("AI_BASE_URL") or "").rstrip("/") + "/chat/completions"
    key = os.environ.get("AI_API_KEY") or ""
    model = model or os.environ.get("ALMANAC_MEASURE_MODEL") or "gpt-5.5"
    if not key or "://" not in url:
        return "", "", "", "No endpoint configured — set AI_BASE_URL and AI_API_KEY."
    return url, key, model, ""


def _render(rows: list[dict], model: str) -> str:
    """Two charts, not one. The renderer shares a single Y axis between yKey and
    y2Key, so seconds and tokens/second cannot sit on the same plot — the
    latency line would flatten against a throughput scale. Paired same-unit
    series instead: median against tail, aggregate against per-stream."""
    latency = {
        "type": "line",
        "title": f"{model}: time to first token as concurrency rises",
        "data": rows,
        "xKey": "concurrency",
        "yKey": "ttft_median",
        "y2Key": "ttft_p95",
        "yFormat": "number",
    }
    throughput = {
        "type": "line",
        "title": f"{model}: throughput as concurrency rises",
        "data": rows,
        "xKey": "concurrency",
        "yKey": "aggregate_tps",
        "y2Key": "per_stream_tps",
        "yFormat": "number",
    }
    table = {
        "title": "Measured on this endpoint, just now",
        "columns": ["Concurrent", "TTFT median", "TTFT p95", "Tok/s per stream", "Aggregate tok/s"],
        "rows": [
            [
                str(r["concurrency"]),
                f"{r['ttft_median']}s",
                f"{r['ttft_p95']}s",
                str(r["per_stream_tps"]),
                str(r["aggregate_tps"]),
            ]
            for r in rows
        ],
    }
    first, last = rows[0], rows[-1]
    change = 100 * (last["per_stream_tps"] / max(first["per_stream_tps"], 1e-9) - 1)
    if change < -5:
        shape = f"each stream slows {abs(change):.0f}% against the single-stream rate"
    elif change > 5:
        shape = (
            f"each stream is {change:.0f}% faster than the single-stream rate — the "
            f"endpoint was not saturated and the lone request paid cold-start cost"
        )
    else:
        shape = "per-stream rate holds roughly flat"
    knee = next((r["concurrency"] for r in rows if r["ttft_p95"] > 2 * first["ttft_median"]), None)
    if knee:
        knee_note = (
            f" The p95 first passes twice the single-stream median at {knee} "
            f"concurrent, which is where interactive traffic starts to feel it."
        )
    else:
        knee_note = (
            f" The p95 never reached twice the single-stream median, so this sweep "
            f"did not find the limit — the endpoint absorbed everything up to "
            f"{last['concurrency']} concurrent. Do not read an operating ceiling "
            f"off this curve; measure higher levels to find where it bends."
        )
    note = (
        f"At {last['concurrency']} concurrent streams aggregate throughput reaches "
        f"{last['aggregate_tps']} tok/s and {shape}. Time to first token moved from "
        f"{first['ttft_median']}s to {last['ttft_median']}s median "
        f"({last['ttft_p95']}s at p95).{knee_note}"
    )
    return (
        "```chart\n" + json.dumps(latency) + "\n```\n\n"
        "```chart\n" + json.dumps(throughput) + "\n```\n\n"
        "```datatable\n" + json.dumps(table) + "\n```\n\n" + note
    )


@tool
async def sweep_plan(concurrency: str = "", samples: int = 0, max_tokens: int = 0) -> str:
    """Agree the sweep before running it, and say what it will cost in time.

    Args:
        concurrency: comma-separated levels, e.g. "1,4,16". Defaults to 1,2,4,8.
        samples: measurements per level. Defaults to 5.
        max_tokens: completion length per request. Defaults to 120.
    """
    levels = _parse_levels(concurrency)
    n_samples = max(1, min(_MAX_SAMPLES, samples or _MIN_SAMPLES))
    n_tokens = max(16, min(_MAX_TOKENS_CAP, max_tokens or _MAX_TOKENS))
    reqs = sum(max(n, n_samples) for n in levels)
    return (
        f"Plan: levels {', '.join(str(n) for n in levels)}; at least {n_samples} samples each; "
        f"{n_tokens}-token completions. That is about {reqs} requests and roughly "
        f"{reqs * 3 // 60 + 1} minute(s).\n\n"
        f"Measure them one level at a time with `measure_level`, reporting each result as it "
        f"lands, then call `plot_curve` with everything collected. Ceilings: "
        f"{_MAX_CONCURRENCY} concurrent, {_MAX_SAMPLES} samples, {_MAX_TOKENS_CAP} tokens."
    )


@tool
async def measure_level(
    concurrency: int, model: str = "", samples: int = 0, max_tokens: int = 0
) -> str:
    """Measure ONE concurrency level. Fast enough to report between steps.

    Args:
        concurrency: how many streams to run at once.
        model: which model to measure. Defaults to the configured one.
        samples: minimum measurements. Defaults to 5.
        max_tokens: completion length. Defaults to 120.
    """
    url, key, model, err = _endpoint(model)
    if err:
        return err
    n = max(1, min(_MAX_CONCURRENCY, int(concurrency or 1)))
    n_samples = max(1, min(_MAX_SAMPLES, samples or _MIN_SAMPLES))
    n_tokens = max(16, min(_MAX_TOKENS_CAP, max_tokens or _MAX_TOKENS))

    res: list[dict] = []
    wall = 0.0
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        while len(res) < n_samples:
            t0 = time.perf_counter()
            res += await asyncio.gather(
                *(_one(client, url, key, model, n_tokens) for _ in range(n))
            )
            wall += time.perf_counter() - t0
    ok = [r for r in res if r["ok"]]
    if not ok:
        return f"concurrency {n}: every request failed against {model}."
    tt = sorted(r["ttft"] for r in ok)
    row = {
        "concurrency": n,
        "ttft_median": round(statistics.median(tt), 2),
        "ttft_p95": round(tt[min(len(tt) - 1, int(0.95 * len(tt)))], 2),
        "aggregate_tps": round(sum(r["toks"] for r in ok) / wall, 1),
        "per_stream_tps": round(statistics.median(r["tps"] for r in ok), 1),
    }
    return (
        f"concurrency {n}: TTFT median {row['ttft_median']}s, p95 {row['ttft_p95']}s, "
        f"{row['per_stream_tps']} tok/s per stream, {row['aggregate_tps']} tok/s aggregate "
        f"({len(ok)}/{len(res)} succeeded).\n\nMEASUREMENT {json.dumps(row)}"
    )


@tool
async def plot_curve(measurements: str, model: str = "") -> str:
    """Chart the levels measured so far.

    Args:
        measurements: the MEASUREMENT json objects collected, one per level.
        model: the model they were measured against, for the titles.
    """
    rows = []
    for m in re.finditer(r"\{[^{}]*\"concurrency\"[^{}]*\}", measurements):
        try:
            rows.append(json.loads(m.group(0)))
        except Exception:
            continue
    rows = sorted({r["concurrency"]: r for r in rows}.values(), key=lambda r: r["concurrency"])
    if not rows:
        return "No measurements to plot — run `measure_level` first."
    return _render(rows, model or "endpoint")
