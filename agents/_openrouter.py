"""The OpenRouter model and provider catalogue.

Public, keyless, and it moves — roughly five new models a week. That is what
makes it worth monitoring and what makes this workspace a demo that is never
stale: there is no fixture to refresh and no key for a reader to obtain.

The catalogue is ~650 KB, so it is cached on disk for an hour. A tool that
refetched it per call would spend most of a conversation waiting, and would be
rude to a free endpoint.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODELS_URL = "https://openrouter.ai/api/v1/models"
PROVIDERS_URL = "https://openrouter.ai/api/v1/providers"

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_TTL_SECONDS = 3600


def _fetch(url: str, name: str) -> dict:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{name}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < _TTL_SECONDS:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # a truncated cache should not be fatal; refetch below
    req = urllib.request.Request(url, headers={"User-Agent": "almanac/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode("utf-8"))
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def models() -> list[dict]:
    return _fetch(MODELS_URL, "models").get("data", [])


def providers() -> list[dict]:
    return _fetch(PROVIDERS_URL, "providers").get("data", [])


def launched(model: dict) -> datetime | None:
    ts = model.get("created")
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def since(days: int) -> list[dict]:
    """Models launched in the last `days`, newest first."""
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    out = [m for m in models() if (d := launched(m)) and d >= cut]
    return sorted(out, key=lambda m: m["created"], reverse=True)


def price_per_million(model: dict, key: str = "prompt") -> float | None:
    """OpenRouter quotes price per token. Per million is the unit people use.

    A negative value is a sentinel, not a price: the five `openrouter/*` router
    entries carry -1 because what they cost is decided when they pick a model.
    Multiplying that by a million produced -$1,000,000 per million tokens in
    the table, which is how it was noticed. None means unknown, and callers
    already handle unknown.

    The single number is also a simplification the source invites: some models
    carry a `pricing.overrides` list with tiered or time-of-day rates. This
    returns the headline rate, which is right for ranking and wrong for a
    quote.
    """
    raw = (model.get("pricing") or {}).get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value * 1_000_000 if value >= 0 else None


def is_router(model: dict) -> bool:
    """A meta-model that forwards to others, so it has no fixed price of its own."""
    pricing = model.get("pricing") or {}
    for key in ("prompt", "completion"):
        try:
            if float(pricing.get(key, 0)) < 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def vendor(model: dict) -> str:
    """The organisation half of `vendor/model-name`."""
    return (model.get("id") or "").split("/", 1)[0] or "unknown"


def is_free(model: dict) -> bool:
    return price_per_million(model, "prompt") == 0


def fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    if v == 0:
        return "free"
    return f"${v:,.2f}" if v >= 0.01 else f"${v:.4f}"


def fmt_context(n: int | None) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n // 1000}K" if n >= 1000 else str(n)
