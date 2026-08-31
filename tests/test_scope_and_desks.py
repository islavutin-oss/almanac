"""The cast, and the subject they stay inside.

Two things this guards:

- Every agent carries the scope note. Without it they answer anything asked,
  in the same confident voice they use for a measured figure — and a reader
  cannot tell a grounded number from a guess, which is the one failure this
  demo exists to avoid.
- Rune is the analysis desk. She absorbed the catalogue tools when Ada was
  retired; if `shared_tools` stops pointing at them she silently loses two
  thirds of what she can answer, with no error anywhere.
"""

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "workspace.yml").read_text())
AGENTS = ROOT / "agents"


def test_the_cast_is_three_desks():
    # Vera public-facing, Rune analysis, Ines writing. Ada merged into Rune.
    assert set(CONFIG["apps"]) == {"advisor", "providers", "editor"}
    assert CONFIG["apps"]["advisor"]["group"] == "customer"
    assert CONFIG["apps"]["providers"]["group"] == "backoffice"


def test_mira_still_reaches_the_catalogue_tools():
    shared = CONFIG["apps"]["providers"].get("shared_tools") or []
    assert any("_catalogue/tools" in s for s in shared), (
        "Rune lost the catalogue desk — she answers only provider questions now"
    )
    assert (AGENTS / "_catalogue" / "tools").is_dir(), "the tools she points at are gone"


def test_every_agent_carries_the_scope_note():
    for app in CONFIG["apps"].values():
        soul = ROOT / app["soul"]
        assert "{{include:../_scope.md}}" in soul.read_text(), f"{soul} has no scope note"


def test_the_scope_note_refuses_without_lecturing():
    text = (AGENTS / "_scope.md").read_text()
    assert "outside" in text.lower()
    # It must offer an alternative, not just decline.
    assert "I can" in text
    # And it must not invite a hedged answer anyway.
    assert "do not answer anyway" in text.lower()


def test_adjacent_subjects_stay_in_scope():
    # Serving hardware, latency budgets and cost modelling are the subject, not
    # exceptions to it. A guard that refuses those makes the demo useless.
    # Normalise wrapping: the note is prose, so a phrase may span two lines.
    text = " ".join((AGENTS / "_scope.md").read_text().lower().split())
    for kept in ("hardware for serving", "latency budgets", "cost modelling"):
        assert kept in text, f"scope note does not keep {kept!r} in bounds"


def test_every_agent_has_openers():
    for app_id, app in CONFIG["apps"].items():
        assert app.get("suggestions"), f"{app_id} has no opening questions"


def test_advisor_has_more_than_one_retrieval_tool():
    # Everything used to route through shortlist, so every answer looked the
    # same. compare() exists for "which of these", a different question.
    src = (AGENTS / "advisor" / "tools" / "advise.py").read_text()
    names = set(re.findall(r"@tool\s*\n\s*async def (\w+)", src))
    assert {"shortlist", "compare"} <= names, names
