"""A digest that opens on a row of zeros teaches the reader to skip the top."""

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


def kpi(out: str) -> list[dict]:
    m = re.search(r"```kpi\n(.*?)\n```", out, re.S)
    assert m, f"no kpi block: {out[:160]}"
    return json.loads(m.group(1))


CHANGE = {
    "have_history": True,
    "from": "2026-01-01",
    "to": "2026-01-08",
    "added": [],
    "removed": [],
    "quality_moves": [],
    "latency_moves": [],
    "price_moves": [
        {"name": "M1", "vendor": "v", "was": 1.0, "now": 0.5, "pct": -50.0},
    ],
}


@pytest.fixture
def cat(monkeypatch):
    import _history

    import agents._catalogue.tools.catalogue as mod

    monkeypatch.setattr(_history, "compare", lambda back=7: dict(CHANGE))
    return mod


def test_a_single_moving_category_is_a_sentence_not_a_lone_card(cat):
    """One card alone is not a dashboard row, it is a number that wandered into
    a box — and the prose beneath already names the cuts."""
    out = run(cat.whats_changed)
    assert "```kpi" not in out
    assert "8 price moves" in out.lower() or "1 price moves" in out.lower()
    assert "```datatable" in out, "the cut detail should survive the shorter form"


def test_two_or_more_categories_do_get_a_row(cat, monkeypatch):
    import _history

    busy = {**CHANGE, "added": [{"name": "N"}]}
    monkeypatch.setattr(_history, "compare", lambda back=7: dict(busy))
    cards = kpi(run(cat.whats_changed))
    assert {c["title"] for c in cards} == {"New", "Price moves"}


def test_every_card_carries_a_nonzero_value(cat, monkeypatch):
    import _history

    busy = {**CHANGE, "added": [{"name": "N"}]}
    monkeypatch.setattr(_history, "compare", lambda back=7: dict(busy))
    assert all(c["value"] != "0" for c in kpi(run(cat.whats_changed)))


def test_nothing_moving_is_a_sentence_not_a_block_of_zeros(cat, monkeypatch):
    import _history

    quiet = {**CHANGE, "price_moves": []}
    monkeypatch.setattr(_history, "compare", lambda back=7: dict(quiet))
    out = run(cat.whats_changed)
    assert "```kpi" not in out, "a quiet day must not emit a row of zeros"
    assert "Nothing moved" in out
    assert "2026-01-01" in out and "2026-01-08" in out


def test_several_moves_all_appear(cat, monkeypatch):
    import _history

    busy = {
        **CHANGE,
        "added": [{"name": "N"}],
        "latency_moves": [{"name": "L", "was": 1.0, "now": 2.0, "pct": 100.0}],
    }
    monkeypatch.setattr(_history, "compare", lambda back=7: dict(busy))
    titles = [c["title"] for c in kpi(run(cat.whats_changed))]
    assert set(titles) == {"New", "Price moves", "Latency moves"}
