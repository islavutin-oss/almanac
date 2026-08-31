"""Publishing the weekly piece to the public blog.

The blog is a directory of markdown files with YAML frontmatter. Publishing is
therefore writing one file — which is the whole reason the site reads articles
off disk rather than out of a TypeScript array. An agent cannot open a pull
request, but it can write a file, and the site picks it up on its next revalidate.

The output directory is configured, never guessed: set ALMANAC_BLOG_DIR. With
it unset the tools say so and write nothing, so a misconfigured deploy fails
loudly at the point of publication instead of quietly filing into /tmp.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from agentino import tool

PUBLIC_BASE = os.environ.get("ALMANAC_BLOG_URL", "https://agentino.co/writing").rstrip("/")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_BODY = 60_000


def blog_dir() -> Path | None:
    raw = os.environ.get("ALMANAC_BLOG_DIR", "").strip()
    return Path(raw).expanduser() if raw else None


def slugify(text: str) -> str:
    """A URL segment that cannot escape the content directory.

    Everything outside [a-z0-9-] becomes a hyphen, so `../../etc/passwd` and
    `a/b` both collapse to something flat. A title that is entirely non-Latin
    would otherwise slugify to the empty string, so it falls back to a hash
    rather than writing `.md`.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = _SLUG_STRIP.sub("-", folded.lower()).strip("-")
    if not cleaned:
        cleaned = "post-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return cleaned[:80].strip("-")


def _quote(value: str) -> str:
    """Frontmatter values are read by a small parser, not a YAML engine. Keep
    them on one line and escape the quote that would end the string early."""
    flat = " ".join(str(value).split())
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(*, title: str, summary: str, body: str, author: str, day: str, draft: bool) -> str:
    lines = [
        "---",
        f"title: {_quote(title)}",
        f"summary: {_quote(summary)}",
        f"date: {day}",
        f"author: {_quote(author)}",
    ]
    if draft:
        lines.append("draft: true")
    lines += ["---", "", body.strip(), ""]
    return "\n".join(lines)


@tool
async def list_published() -> str:
    """List the articles already on the blog, newest first.

    Read this before writing so you do not publish the same piece twice.
    """
    directory = blog_dir()
    if directory is None:
        return "ALMANAC_BLOG_DIR is not set, so I cannot see the blog."
    if not directory.is_dir():
        return f"No blog directory at {directory}."

    rows = []
    for path in sorted(directory.glob("*.md")):
        head = path.read_text(encoding="utf-8", errors="replace")[:1200]
        title = re.search(r'^title:\s*"?(.*?)"?\s*$', head, re.M)
        day = re.search(r"^date:\s*(\S+)", head, re.M)
        author = re.search(r'^author:\s*"?(.*?)"?\s*$', head, re.M)
        rows.append(
            f"{day.group(1) if day else '????-??-??'}  {path.stem}"
            f"  — {title.group(1) if title else path.stem}"
            f"{'  [' + author.group(1) + ']' if author else ''}"
        )
    if not rows:
        return "The blog has no articles yet."
    rows.sort(reverse=True)
    return f"{len(rows)} article(s) published:\n" + "\n".join(rows)


@tool
async def publish_article(
    title: str,
    summary: str,
    body: str,
    author: str = "Ines · Almanac",
    slug: str = "",
    day: str = "",
    draft: bool = False,
    replace: bool = False,
) -> str:
    """Publish an article to the blog and return its public URL.

    title    the headline, as it appears on the page
    summary  one or two sentences for the index card and the page description
    body     the article itself, in markdown — no title heading, the page adds one
    author   byline; keep the agent's name in it so readers know what wrote this
    slug     URL segment; derived from the title when empty
    day      publication date as YYYY-MM-DD; today when empty
    draft    write the file but keep it off the index
    replace  overwrite an article that already exists at this slug
    """
    directory = blog_dir()
    if directory is None:
        return (
            "I cannot publish: ALMANAC_BLOG_DIR is not set. Nothing was written. "
            "Point it at the blog's content directory and try again."
        )

    title = " ".join(str(title).split())
    if not title:
        return "An article needs a title. Nothing was written."
    body = str(body).strip()
    if len(body) < 200:
        return (
            f"The body is {len(body)} characters — too short to be an article. Nothing was written."
        )
    if len(body) > _MAX_BODY:
        return (
            f"The body is {len(body)} characters, over the {_MAX_BODY} limit. Nothing was written."
        )

    day = day.strip() or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return f"'{day}' is not a YYYY-MM-DD date. Nothing was written."

    name = slugify(slug or title)
    target = directory / f"{name}.md"
    # slugify cannot emit a separator, but assert the result rather than trust it.
    if target.parent.resolve() != directory.resolve():
        return "That slug does not resolve inside the blog directory. Nothing was written."
    if target.exists() and not replace:
        return (
            f"'{name}' is already published — call list_published to see it. "
            "Pass replace=true only if you mean to overwrite it. Nothing was written."
        )

    directory.mkdir(parents=True, exist_ok=True)
    text = render(title=title, summary=summary, body=body, author=author, day=day, draft=draft)
    # Write beside the target and rename, so a reader never sees half a file.
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)

    url = f"{PUBLIC_BASE}/{name}"
    words = len(body.split())
    state = "saved as a draft (not on the index)" if draft else "published"
    return f"{state}: {title}\n{url}\n{words} words, dated {day}, by {author}."
