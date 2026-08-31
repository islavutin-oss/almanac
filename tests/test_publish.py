"""The publishing tool writes files into a public directory, so its guards
matter more than its happy path."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def publish(tmp_path, monkeypatch):
    monkeypatch.setenv("ALMANAC_BLOG_DIR", str(tmp_path))
    monkeypatch.setenv("ALMANAC_BLOG_URL", "https://example.test/writing")
    sys.modules.pop("agents.editor.tools.publish", None)
    mod = importlib.import_module("agents.editor.tools.publish")
    return importlib.reload(mod)


def call(fn, **kw):
    import asyncio

    return asyncio.run(fn.fn(**kw) if hasattr(fn, "fn") else fn(**kw))


BODY = "A real article body. " * 40


# --- slugs -----------------------------------------------------------------


def test_slug_cannot_contain_a_separator(publish):
    for hostile in ["../../etc/passwd", "a/b", "..\\win", "/abs/path", "....//x"]:
        assert "/" not in publish.slugify(hostile)
        assert "\\" not in publish.slugify(hostile)
        assert not publish.slugify(hostile).startswith(".")


def test_slug_of_untransliterable_title_is_not_empty(publish):
    # Would otherwise write a file called ".md".
    assert publish.slugify("性能测试").startswith("post-")


def test_slug_is_bounded(publish):
    assert len(publish.slugify("word " * 200)) <= 80


# --- refusals --------------------------------------------------------------


def test_unset_directory_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("ALMANAC_BLOG_DIR", raising=False)
    sys.modules.pop("agents.editor.tools.publish", None)
    mod = importlib.import_module("agents.editor.tools.publish")
    importlib.reload(mod)
    out = call(mod.publish_article, title="T", summary="s", body=BODY)
    assert "ALMANAC_BLOG_DIR is not set" in out
    assert list(tmp_path.glob("*.md")) == []


def test_short_body_is_refused(publish, tmp_path):
    out = call(publish.publish_article, title="T", summary="s", body="too short")
    assert "too short" in out
    assert list(tmp_path.glob("*.md")) == []


def test_empty_title_is_refused(publish, tmp_path):
    out = call(publish.publish_article, title="   ", summary="s", body=BODY)
    assert "needs a title" in out
    assert list(tmp_path.glob("*.md")) == []


def test_bad_date_is_refused(publish, tmp_path):
    out = call(publish.publish_article, title="T", summary="s", body=BODY, day="last tuesday")
    assert "not a YYYY-MM-DD date" in out
    assert list(tmp_path.glob("*.md")) == []


def test_oversized_body_is_refused(publish, tmp_path):
    out = call(publish.publish_article, title="T", summary="s", body="x " * 40_000)
    assert "over the" in out
    assert list(tmp_path.glob("*.md")) == []


def test_republishing_the_same_slug_needs_replace(publish, tmp_path):
    call(publish.publish_article, title="Serving costs", summary="s", body=BODY)
    again = call(publish.publish_article, title="Serving costs", summary="s", body="B " * 200)
    assert "already published" in again
    assert (tmp_path / "serving-costs.md").read_text().count("A real article body") > 0


def test_replace_overwrites(publish, tmp_path):
    call(publish.publish_article, title="Serving costs", summary="s", body=BODY)
    out = call(
        publish.publish_article,
        title="Serving costs",
        summary="s",
        body="Rewritten. " * 40,
        replace=True,
    )
    assert "published" in out
    assert "Rewritten." in (tmp_path / "serving-costs.md").read_text()


# --- what lands on disk ----------------------------------------------------


def test_published_file_has_frontmatter_and_url(publish, tmp_path):
    out = call(
        publish.publish_article,
        title="What a GPU-hour buys",
        summary="Prices moved.",
        body=BODY,
        day="2026-08-14",
    )
    path = tmp_path / "what-a-gpu-hour-buys.md"
    text = path.read_text()
    assert text.startswith("---\n")
    assert 'title: "What a GPU-hour buys"' in text
    assert "date: 2026-08-14" in text
    assert 'author: "Ines · Almanac"' in text
    assert "https://example.test/writing/what-a-gpu-hour-buys" in out


def test_draft_is_marked_and_reported_as_a_draft(publish, tmp_path):
    out = call(publish.publish_article, title="Draft piece", summary="s", body=BODY, draft=True)
    assert "draft: true" in (tmp_path / "draft-piece.md").read_text()
    assert "draft" in out


def test_quotes_in_a_title_do_not_break_frontmatter(publish, tmp_path):
    call(
        publish.publish_article, title='The "cheap" model', summary='He said "no": twice', body=BODY
    )
    text = (tmp_path / "the-cheap-model.md").read_text()
    assert 'title: "The \\"cheap\\" model"' in text
    # The summary keeps its colon inside the quotes rather than ending the value.
    assert 'summary: "He said \\"no\\": twice"' in text


def test_newlines_in_a_summary_are_flattened(publish, tmp_path):
    call(publish.publish_article, title="T", summary="one\ntwo", body=BODY)
    head = (tmp_path / "t.md").read_text().split("---")[1]
    assert 'summary: "one two"' in head
    assert head.count("summary:") == 1


def test_no_temporary_file_is_left_behind(publish, tmp_path):
    call(publish.publish_article, title="T", summary="s", body=BODY)
    assert list(tmp_path.glob("*.tmp")) == []


# --- listing ---------------------------------------------------------------


def test_listing_is_newest_first(publish):
    call(publish.publish_article, title="Older", summary="s", body=BODY, day="2026-01-01")
    call(publish.publish_article, title="Newer", summary="s", body=BODY, day="2026-06-01")
    out = call(publish.list_published)
    assert out.index("Newer") < out.index("Older")
    assert "2 article(s)" in out


def test_listing_an_empty_blog_says_so(publish):
    assert "no articles yet" in call(publish.list_published)


def test_listing_without_configuration_says_so(monkeypatch):
    monkeypatch.delenv("ALMANAC_BLOG_DIR", raising=False)
    sys.modules.pop("agents.editor.tools.publish", None)
    mod = importlib.reload(importlib.import_module("agents.editor.tools.publish"))
    assert "not set" in call(mod.list_published)
