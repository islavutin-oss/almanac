"""A statistic computed after truncation is a property of the chart, not of the
catalogue. This published '15 models' where the real figure was 80."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))


def run(fn, **kw):
    return asyncio.run(fn.fn(**kw) if hasattr(fn, "fn") else fn(**kw))


def chart(out: str) -> dict:
    m = re.search(r"```chart\n(.*?)\n```", out, re.S)
    assert m, f"no chart: {out[:160]}"
    return json.loads(m.group(1))


@pytest.fixture
def cat(monkeypatch):
    import agents._catalogue.tools.catalogue as mod

    # 30 models that all qualify as "500K+ context under $1/M".
    models = [
        {
            "id": f"v/m{i}",
            "name": f"Model {i}",
            "context_length": 600_000 + i,
            "pricing": {"prompt": "0.0000005", "completion": "0.000001"},
        }
        for i in range(30)
    ]
    monkeypatch.setattr(mod, "models", lambda: models)
    return mod


def test_count_is_over_all_matches_not_the_plotted_slice(cat):
    """With limit=5 the chart shows five points, but thirty models qualify."""
    out = run(cat.price_vs_context, limit=5)
    assert len(chart(out)["data"]) == 5, "the chart should still be truncated"
    assert "30 of 30 listings" in out, f"count was taken after truncation: {out[-160:]}"


def test_truncation_is_disclosed(cat):
    out = run(cat.price_vs_context, limit=5)
    assert "plots the 5" in out


def test_no_truncation_note_when_everything_fits(cat):
    out = run(cat.price_vs_context, limit=100)
    assert "plots the" not in out
    assert len(chart(out)["data"]) == 30


def test_title_states_shown_and_matched(cat):
    assert "5 of 30 models" in chart(run(cat.price_vs_context, limit=5))["title"]
