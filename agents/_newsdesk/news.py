"""Reading the week in inference, and not repeating yourself.

Same shape as the analyst desk that files the daily digest on another
workspace: read several feeds, compare against what was already reported, and
only write about what is new. The dedup store is the part that makes a daily
digest survivable — without it, day three is day two with different wording.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from agentino import tool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_DB = Path(__file__).resolve().parents[2] / ".cache" / "signals.sqlite"

# Feeds that actually carry inference and deployment material, verified to
# parse. Vendor blogs for what shipped; infrastructure blogs for how it is
# run, which is the half most AI newsletters skip.
FEEDS: dict[str, str] = {
    # Labs — what shipped
    "OpenAI": "https://openai.com/blog/rss.xml",
    "Google AI": "https://blog.google/technology/ai/rss/",
    "Qwen": "https://qwenlm.github.io/blog/index.xml",
    # Serving stacks. A vLLM or SGLang release *is* inference news — it is
    # where throughput and memory behaviour actually change, and none of the
    # vendor blogs cover it.
    "vLLM": "https://github.com/vllm-project/vllm/releases.atom",
    "SGLang": "https://github.com/sgl-project/sglang/releases.atom",
    "llama.cpp": "https://github.com/ggml-org/llama.cpp/releases.atom",
    "TensorRT-LLM": "https://github.com/NVIDIA/TensorRT-LLM/releases.atom",
    "llm-d": "https://github.com/llm-d/llm-d/releases.atom",
    # Serving and hardware — how it is run, which is the half most AI
    # newsletters skip and the half that decides a bill
    "NVIDIA": "https://developer.nvidia.com/blog/feed/",
    "Together AI": "https://www.together.ai/blog/rss.xml",
    "Meta Engineering": "https://engineering.fb.com/feed/",
    "AWS ML": "https://aws.amazon.com/blogs/machine-learning/feed/",
    "Cloudflare": "https://blog.cloudflare.com/rss/",
    "PyTorch": "https://pytorch.org/blog/feed.xml",
    # Benchmarks are the only public numbers on serving performance that are
    # not published by the vendor being measured.
    "MLCommons": "https://mlcommons.org/feed/",
    # Commentary worth reading
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "SemiAnalysis": "https://semianalysis.com/feed/",
    "Hacker News": "https://news.ycombinator.com/rss",
    # Chinese-language sources. Much of the interesting deployment and
    # cost-of-inference writing appears here first and is never translated;
    # the editor renders anything used into English.
    "量子位 QbitAI": "https://www.qbitai.com/feed",
    "InfoQ 中国": "https://www.infoq.cn/feed",
    "OSCHINA": "https://www.oschina.net/news/rss",
    "Qwen 中文": "https://qwenlm.github.io/zh/blog/index.xml",
}

# Sources whose items arrive in Chinese. Used to tell the editor what needs
# translating, and to keep the scoring honest — an English keyword list scores
# every Chinese headline at zero.
CHINESE_SOURCES = {"量子位 QbitAI", "InfoQ 中国", "OSCHINA", "Qwen 中文"}

# Anthropic publishes no feed — every documented path 404s — so their releases
# arrive here second-hand, usually via Hacker News.

# Terms that mark an item as being about running models rather than about AI
# in general. Weighted, because "inference" in a title is a stronger signal
# than "GPU" buried in a summary.
RELEVANCE: dict[str, int] = {
    # inference and serving
    "inference": 5,
    "serving": 4,
    "throughput": 4,
    "latency": 4,
    "tokens/s": 5,
    "tokens per second": 5,
    "quantization": 4,
    "quantized": 4,
    "kv cache": 5,
    "batching": 3,
    "speculative decoding": 5,
    "vllm": 5,
    "sglang": 5,
    "tensorrt": 5,
    "triton": 3,
    "context window": 4,
    "distillation": 3,
    "fine-tun": 2,
    "deployment": 3,
    "self-host": 4,
    "on-device": 3,
    # hardware
    "gpu": 4,
    "tpu": 4,
    "accelerator": 4,
    "h100": 5,
    "h200": 5,
    "b200": 5,
    "blackwell": 5,
    "mi300": 5,
    "nvlink": 4,
    "rdma": 4,
    "interconnect": 3,
    "cuda": 3,
    "datacenter": 2,
    "cluster": 2,
    # models and providers
    "open weights": 4,
    "open-weight": 4,
    "benchmark": 2,
    "pricing": 3,
    "price": 2,
    "per million": 4,
    "api": 1,
    "endpoint": 2,
    "provider": 2,
    "release": 1,
    "launch": 1,
    "model card": 3,
    # Chinese equivalents, so the same filter works on both halves of the
    # feed list rather than silently discarding one of them.
    "推理": 5,
    "部署": 4,
    "显存": 5,
    "算力": 4,
    "量化": 4,
    "吞吐": 5,
    "延迟": 4,
    "大模型": 2,
    "开源模型": 3,
    "英伟达": 3,
    "芯片": 3,
    "定价": 3,
    "降价": 4,
    "token": 2,
    "并发": 3,
    "本地部署": 5,
}


def relevance(item: dict) -> int:
    """How much an item is about running models, rather than about AI at large.

    A crude weighted keyword count, and deliberately so: the alternative is
    asking a model to judge every headline, which costs a call per item and is
    no more accurate on titles this short. Title matches count double because
    a term in a headline is what the piece is about.
    """
    title = (item.get("title") or "").lower()
    summary = (item.get("summary") or "").lower()
    score = 0
    for term, weight in RELEVANCE.items():
        if term in title:
            score += weight * 2
        elif term in summary:
            score += weight
    return score


def _connect() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(
        "CREATE TABLE IF NOT EXISTS signals ("
        " url TEXT PRIMARY KEY, title TEXT, source TEXT, at TEXT)"
    )
    return con


def _parse(xml: str, limit: int) -> list[dict]:
    items = re.findall(r"<item[^>]*>(.*?)</item>", xml, re.DOTALL) or re.findall(
        r"<entry[^>]*>(.*?)</entry>", xml, re.DOTALL
    )
    out = []
    for it in items[:limit]:
        title = re.search(r"<title[^>]*>(.*?)</title>", it, re.DOTALL)
        link = re.search(r'<link[^>]*href="([^"]+)"', it) or re.search(
            r"<link[^>]*>(.*?)</link>", it, re.DOTALL
        )
        desc = re.search(r"<description[^>]*>(.*?)</description>", it, re.DOTALL) or re.search(
            r"<summary[^>]*>(.*?)</summary>", it, re.DOTALL
        )

        def clean(m, n=1):
            if not m:
                return ""
            s = m.group(n)
            # CDATA first. `<[^>]+>` sees `<![CDATA[ … ]]>` as a single tag,
            # because the first `>` it finds is the one closing the section —
            # so stripping tags first deletes the entire title. Every OpenAI
            # headline came back blank until this order was fixed.
            s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.DOTALL)
            return re.sub(r"<[^>]+>", "", s).strip()

        t = clean(title)
        if t:
            out.append({"title": t, "link": clean(link, 1), "summary": clean(desc)[:220]})
    return out


@tool
async def read_feed(url: str, limit: int = 10) -> str:
    """Recent items from one RSS or Atom feed.

    Args:
        url: the feed URL.
        limit: how many items to return.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "almanac/0.1"})
            r.raise_for_status()
            items = _parse(r.text, limit)
    except Exception as e:
        return f"Could not read {url}: {type(e).__name__}"
    return json.dumps(items, ensure_ascii=False) if items else f"No items at {url}."


@tool
async def scan_sources(per_feed: int = 5) -> str:
    """Sweep every configured feed at once.

    The starting point for a digest — one call rather than eight.

    Args:
        per_feed: items to take from each feed.
    """
    import asyncio

    import httpx

    async def one(name: str, url: str) -> tuple[str, list[dict] | str]:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "almanac/0.1"})
                r.raise_for_status()
                return name, _parse(r.text, per_feed)
        except Exception as e:
            return name, f"unavailable ({type(e).__name__})"

    results = await asyncio.gather(*(one(n, u) for n, u in FEEDS.items()))
    payload = {n: v for n, v in results}
    ok = sum(1 for v in payload.values() if isinstance(v, list))
    return json.dumps({"feeds_read": ok, "of": len(FEEDS), "items": payload}, ensure_ascii=False)


@tool
async def already_reported(days: int = 14) -> str:
    """Stories already written about, so the digest does not repeat itself.

    Call this before drafting. A digest that recycles yesterday's finding is
    worse than a short one.

    Args:
        days: how far back to look.
    """
    with _connect() as con:
        rows = con.execute(
            "SELECT title, url, source, at FROM signals WHERE at >= datetime('now', ?) "
            "ORDER BY at DESC LIMIT 200",
            (f"-{int(days)} days",),
        ).fetchall()
    if not rows:
        return "Nothing reported yet — everything you find is new."
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)


@tool
async def mark_reported(url: str, title: str = "", source: str = "") -> str:
    """Record a story as covered, so tomorrow's digest skips it.

    Args:
        url: the story's link — the identity used for dedup.
        title: its headline.
        source: which feed it came from.
    """
    if not url:
        return "A URL is required; it is what dedup matches on."
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO signals (url, title, source, at) VALUES (?, ?, ?, ?)",
            (
                url.rstrip("/"),
                title,
                source,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        con.commit()
    return f"Recorded. Future digests will skip {url}."


@tool
async def scan_inference(min_score: int = 4, per_feed: int = 12, limit: int = 25) -> str:
    """Sweep every feed and keep only what is about running models.

    The feeds carry plenty that is not — travel search, feature stores, general
    company news. This scores each item on inference, hardware and provider
    terms and drops the rest, so a digest starts from candidates rather than
    from noise.

    Args:
        min_score: relevance floor; lower it if the sweep comes back thin.
        per_feed: items to pull from each feed before scoring.
        limit: how many survivors to return.
    """
    import asyncio

    import httpx

    async def one(name: str, url: str):
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "almanac/0.1"})
                r.raise_for_status()
                return [dict(i, source=name) for i in _parse(r.text, per_feed)]
        except Exception:
            return []

    batches = await asyncio.gather(*(one(n, u) for n, u in FEEDS.items()))
    scored = []
    for items in batches:
        for i in items:
            s = relevance(i)
            if s >= min_score:
                scored.append(dict(i, score=s))
    scored.sort(key=lambda i: -i["score"])

    if not scored:
        return (
            "Nothing in the feeds scored as inference-related just now. That is "
            "a quiet day, not a failure — say so rather than padding."
        )
    return json.dumps(
        {"kept": len(scored), "showing": min(limit, len(scored)), "items": scored[:limit]},
        ensure_ascii=False,
    )
