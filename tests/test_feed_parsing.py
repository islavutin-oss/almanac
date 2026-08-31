"""Parsing the XML feeds actually serve, not the XML they document.

The regression here was silent and total: every OpenAI headline came back blank
for a while. Their RSS wraps titles in CDATA, and stripping tags before
unwrapping it deletes the whole title — `<[^>]+>` sees `<![CDATA[ … ]]>` as one
tag, because the first `>` it meets is the one closing the section. Nothing
errored; the digest simply had untitled items.

The repo README claimed a test covered this. It did not, until now.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "agents" / "_newsdesk"))

import news  # noqa: E402


def feed(*items: str) -> str:
    return "<rss><channel>" + "".join(items) + "</channel></rss>"


def item(title: str, link: str = "https://example.test/a", desc: str = "d") -> str:
    return (
        f"<item><title>{title}</title><link>{link}</link><description>{desc}</description></item>"
    )


def test_a_cdata_title_survives_tag_stripping():
    out = news._parse(feed(item("<![CDATA[Jalapeño's first results]]>")), limit=5)
    assert out, "the item vanished entirely"
    assert out[0]["title"] == "Jalapeño's first results"


def test_a_plain_title_is_unchanged():
    out = news._parse(feed(item("A plain headline")), limit=5)
    assert out[0]["title"] == "A plain headline"


def test_markup_inside_a_title_is_stripped_but_the_text_kept():
    out = news._parse(feed(item("Model <b>v2</b> ships")), limit=5)
    assert out[0]["title"] == "Model v2 ships"


def test_cdata_wrapping_markup_keeps_the_text():
    # Both paths at once: unwrap the section, then strip the tags inside it.
    out = news._parse(feed(item("<![CDATA[Model <b>v2</b> ships]]>")), limit=5)
    assert out[0]["title"] == "Model v2 ships"


def test_a_cdata_description_survives_too():
    out = news._parse(feed(item("t", desc="<![CDATA[Body <i>text</i>]]>")), limit=5)
    assert "Body text" in out[0]["summary"] or "Body text" in str(out[0])


def test_limit_is_honoured():
    out = news._parse(feed(*[item(f"t{i}") for i in range(8)]), limit=3)
    assert len(out) == 3
