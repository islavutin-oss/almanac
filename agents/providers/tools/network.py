"""The providers desk — who serves the models, and from where."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from agentino import tool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _openrouter import providers  # noqa: E402


def _hq(p: dict) -> str:
    return (p.get("headquarters") or "unknown").strip() or "unknown"


@tool
async def provider_count() -> str:
    """How many providers serve the platform, and how concentrated they are."""
    ps = providers()
    hqs = Counter(_hq(p) for p in ps)
    dcs = Counter()
    for p in ps:
        for d in p.get("datacenters") or []:
            dcs[str(d)] += 1
    cards = [
        {"title": "Providers", "value": str(len(ps)), "subtitle": "serving OpenRouter"},
        {
            "title": "Jurisdictions",
            "value": str(len([k for k in hqs if k != "unknown"])),
            "subtitle": "distinct headquarters",
        },
        {"title": "Datacenter regions", "value": str(len(dcs)), "subtitle": "declared"},
    ]
    return f"```kpi\n{json.dumps(cards)}\n```"


@tool
async def jurisdictions(top: int = 10) -> str:
    """Where providers are headquartered.

    This is the question behind "where does my prompt actually go" — the
    catalogue is one API, the legal surface behind it is not.

    Args:
        top: how many jurisdictions to show.
    """
    counts = Counter(_hq(p) for p in providers() if _hq(p) != "unknown")
    if not counts:
        return "No provider declares a headquarters."
    data = [{"country": k, "providers": v} for k, v in counts.most_common(top)]
    spec = {
        "type": "pie",
        "title": "Providers by headquarters",
        "data": data,
        "xKey": "country",
        "yKey": "providers",
    }
    lead = data[0]
    total = sum(counts.values())
    share = round(100.0 * lead["providers"] / total, 1)
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"{lead['country']} hosts the most ({lead['providers']}, {share}% of those that declare one)."
    )


@tool
async def datacenter_spread(top: int = 12) -> str:
    """Which datacenter regions providers declare.

    Args:
        top: how many regions to show.
    """
    counts: Counter[str] = Counter()
    for p in providers():
        for d in p.get("datacenters") or []:
            counts[str(d)] += 1
    if not counts:
        return "No provider declares a datacenter region."
    data = [{"region": k, "providers": v} for k, v in counts.most_common(top)]
    spec = {
        "type": "bar",
        "title": "Declared datacenter regions",
        "data": data,
        "xKey": "region",
        "yKey": "providers",
    }
    return (
        f"```chart\n{json.dumps(spec)}\n```\n\n"
        f"{len(counts)} distinct regions are declared across the network."
    )


@tool
async def transparency_gaps() -> str:
    """Providers that publish neither a privacy policy nor terms.

    A provider you cannot read the terms of is a provider you cannot assess.
    """
    missing = [
        p
        for p in providers()
        if not p.get("privacy_policy_url") and not p.get("terms_of_service_url")
    ]
    ps = providers()
    if not missing:
        return f"All {len(ps)} providers publish a privacy policy or terms."
    spec = {
        "title": f"Providers publishing neither policy nor terms ({len(missing)} of {len(ps)})",
        "columns": ["Provider", "Headquarters", "Status page"],
        "rows": [
            [p.get("name") or p.get("slug"), _hq(p), "yes" if p.get("status_page_url") else "no"]
            for p in missing[:20]
        ],
    }
    return (
        f"```datatable\n{json.dumps(spec)}\n```\n\n"
        f"{len(missing)} of {len(ps)} providers publish neither document."
    )
