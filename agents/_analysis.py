"""Artificial Analysis — independent quality and speed measurements.

OpenRouter answers what a model costs and who serves it. It says nothing about
whether the model is any good or how fast it responds, and those are the other
two thirds of the decision. Artificial Analysis measures both.

It needs an API key, unlike OpenRouter. That key is a deployment detail, not a
repository one: without it every function here returns None and the desks say
plainly that the measurements are unavailable, rather than failing or — worse —
inventing numbers.

    export ARTIFICIAL_ANALYSIS_API_KEY=...

A free key is issued at artificialanalysis.ai.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "analysis.json"
_TTL_SECONDS = 6 * 3600  # measurements move slowly; the endpoint is metered


def available() -> bool:
    return bool(os.getenv("ARTIFICIAL_ANALYSIS_API_KEY"))


def _load_cache() -> list[dict] | None:
    if _CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _TTL_SECONDS:
        try:
            return json.loads(_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def models() -> list[dict] | None:
    """Measured models, or None when no key is configured or the call fails.

    None is deliberately different from an empty list: empty means "measured
    nothing", None means "we cannot see". A desk must be able to tell those
    apart, because only one of them is worth reporting as a finding.
    """
    cached = _load_cache()
    if cached is not None:
        return cached
    key = os.getenv("ARTIFICIAL_ANALYSIS_API_KEY")
    if not key:
        return None
    req = urllib.request.Request(API_URL, headers={"x-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    data = payload.get("data", payload if isinstance(payload, list) else [])
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _norm(name: str) -> str:
    """Reduce a model name to something comparable across the two sources.

    Punctuation is dropped rather than mapped: the aim is a confident match or
    none at all, because a wrong join would attach one model's latency to
    another's price and nothing downstream would notice.
    """
    s = (name or "").lower().rsplit("/", 1)[-1]
    for ch in "-_.: ":
        s = s.replace(ch, "")
    return s


def index() -> dict[str, dict]:
    """Measurements keyed by normalised model name, or empty when unavailable."""
    rows = models()
    if not rows:
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        for field in ("slug", "name", "id", "model_name"):
            v = r.get(field)
            if isinstance(v, str) and v:
                out.setdefault(_norm(v), r)
    return out


def metric(row: dict, *names: str) -> float | None:
    """First numeric value among `names`, searched one level deep.

    The payload nests some measurements under `evaluations` and some at the
    top level, and the shape has changed before. Naming several candidates and
    taking the first that is a number survives that without a schema.
    """
    for n in names:
        v = row.get(n)
        if isinstance(v, (int, float)):
            return float(v)
    for sub in ("evaluations", "median", "metrics", "performance", "pricing"):
        block = row.get(sub)
        if isinstance(block, dict):
            for n in names:
                v = block.get(n)
                if isinstance(v, (int, float)):
                    return float(v)
    return None


# Metric names as they appear in the payload, and the short keys the tools use.
# Kept here so a shape change is fixed once rather than in every tool.
_FIELDS: dict[str, tuple[str, ...]] = {
    "quality": ("artificial_analysis_intelligence_index", "intelligence_index"),
    "coding": ("artificial_analysis_coding_index", "coding_index"),
    "agentic": ("terminalbench_v2_1",),
    "tool_use": ("tau_banking",),
    "reasoning": ("gpqa",),
    "hard": ("hle",),
    "science": ("scicode",),
    "long_context": ("lcr",),
    "tokens_per_sec": ("median_output_tokens_per_second",),
    "ttft": ("median_time_to_first_token_seconds",),
    "ttfat": ("median_time_to_first_answer_token",),
    "price_in": ("price_1m_input_tokens",),
    "price_out": ("price_1m_output_tokens",),
    "price_blended": ("price_1m_blended_3_to_1",),
}

# Evals published as a 0-1 fraction. Reported as percentages so a reader is not
# comparing 0.53 against an index of 63 in the same table.
_FRACTIONS = {"agentic", "tool_use", "reasoning", "hard", "science", "long_context"}

# The endpoint encodes "we did not measure this" as 0 rather than null for the
# performance figures — 1154 of 1642 latency rows are a flat zero. A zero TTFT
# is not physically possible, and left alone it sorts every unmeasured model to
# the top of a latency ranking. Treated as missing.
#
# Deliberately not applied to the evals: a model can genuinely score zero on a
# benchmark, and discarding that would hide a real result.
_ZERO_MEANS_MISSING = {"ttft", "ttfat", "tokens_per_sec"}


def metrics(row: dict | None) -> dict[str, float | None]:
    """Every measurement for one model, under stable short keys.

    Returns all keys, with None where the measurement is absent — about a third
    of the catalogue is unmeasured and a missing eval must not read as a zero.
    """
    out: dict[str, float | None] = {}
    for key, names in _FIELDS.items():
        v = metric(row, *names) if row else None
        if v is not None and key in _ZERO_MEANS_MISSING and v == 0:
            v = None
        if v is not None and key in _FRACTIONS:
            v = v * 100.0
        out[key] = v
    return out
