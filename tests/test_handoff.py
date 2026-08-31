"""Handing off to a person — an offer, not a capture.

The demo collects nothing. There is no form and no address book: `talk_to_a_human`
prints Iliya's contact routes and the visitor decides whether to write. Holding
strangers' contact details would need a lawful basis, a retention policy and
somewhere safe to keep them, none of which belongs in a demo.

These tests exist so nobody reintroduces a form because it looks like a
conversion win.
"""

import asyncio
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))


def run(fn, **kw):
    # @tool wraps the coroutine in a Tool object; .fn is the original.
    return asyncio.run(fn.fn(**kw) if hasattr(fn, "fn") else fn(**kw))


@pytest.fixture
def advise(monkeypatch):
    monkeypatch.setenv("ADVISOR_CONTACT_EMAIL", "someone@example.test")
    monkeypatch.setenv("ADVISOR_CONTACT_TELEGRAM", "@someone")
    monkeypatch.setenv("ADVISOR_CONTACT_LINKEDIN", "https://example.test/in/someone")
    mod = importlib.import_module("agents.advisor.tools.advise")
    return importlib.reload(mod)


def block(out, kind):
    m = re.search(rf"```{kind}\n(.*?)```", out, re.S)
    assert m, f"no {kind} block in: {out[:200]}"
    return json.loads(m.group(1))


def test_the_handoff_is_a_card(advise):
    spec = block(run(advise.talk_to_a_human, topic="tail latency in one region"), "insight")
    assert spec["headline"]
    assert spec["body"]


def test_it_collects_nothing(advise):
    out = run(advise.talk_to_a_human, topic="a bill under real traffic")
    assert "```form" not in out, "a form means collecting contact details — deliberately gone"
    assert not hasattr(advise, "record_enquiry"), "the capture tool must stay removed"


def test_every_configured_route_is_offered(advise):
    spec = block(run(advise.talk_to_a_human, topic="x"), "insight")
    body = spec["body"]
    assert "someone@example.test" in body
    assert "@someone" in body
    assert "example.test/in/someone" in body


def test_the_cta_opens_the_primary_route(advise):
    spec = block(run(advise.talk_to_a_human, topic="x"), "insight")
    assert spec["cta"]["href"] == "mailto:someone@example.test"
    assert spec["cta"]["label"]


def test_the_topic_is_reflected_back(advise):
    topic = "serving a 70B at 200 rps"
    spec = block(run(advise.talk_to_a_human, topic=topic), "insight")
    assert topic.lower() in spec["body"].lower()


def test_it_degrades_to_telegram_then_linkedin(monkeypatch):
    monkeypatch.delenv("ADVISOR_CONTACT_EMAIL", raising=False)
    monkeypatch.setenv("ADVISOR_CONTACT_TELEGRAM", "@someone")
    monkeypatch.delenv("ADVISOR_CONTACT_LINKEDIN", raising=False)
    mod = importlib.reload(importlib.import_module("agents.advisor.tools.advise"))
    spec = block(run(mod.talk_to_a_human, topic="x"), "insight")
    assert spec["cta"]["href"] == "https://t.me/someone"


def test_no_contact_configured_still_returns_a_useful_card(monkeypatch):
    for k in ("ADVISOR_CONTACT_EMAIL", "ADVISOR_CONTACT_TELEGRAM", "ADVISOR_CONTACT_LINKEDIN"):
        monkeypatch.delenv(k, raising=False)
    mod = importlib.reload(importlib.import_module("agents.advisor.tools.advise"))
    spec = block(run(mod.talk_to_a_human, topic="x"), "insight")
    assert spec["body"], "the card must still explain why a person helps"
    assert "cta" not in spec, "no route configured means no button to nowhere"
