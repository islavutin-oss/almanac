# Almanac

A workspace that watches LLM inference: what launched, what it costs, how fast
it runs, and who serves it.

Built on [runspace](https://github.com/islavutin-oss/runspace) and
[agentino](https://github.com/islavutin-oss/agentino).

## What it reads

| Source | Gives | Key |
|---|---|---|
| OpenRouter | ~400 models, ~105 providers — price, context, jurisdiction | none |
| Artificial Analysis | ~620 measured — quality index, throughput, latency | free key |
| 22 RSS feeds | inference, hardware and provider news; four Chinese-language | none |

The join is the point: ~150 models carry list price *and* independent
measurements together, which neither source publishes on its own.

## The agents

- **Vera** — front office, and the only agent a visitor talks to. Narrows four
  hundred models to two or three. When a question turns on something the data
  cannot settle — a contract, a deadline, a judgement call — she says so and
  points at a person instead of guessing.
- **Rune** — the analysis desk. The catalogue (price, context, measured quality
  and speed) and the providers serving it (where they are, what they publish).
  She records a snapshot every morning, because nothing upstream keeps history,
  and files the daily read to the channel at 07:00.
- **Ines** — the editor. Writes for the public blog off the same feeds and
  numbers, up to one article a day, and publishes nothing on a day that did not
  earn one.

## Running it

```bash
pip install "runspace[agentino,workspace,server]"

export AI_BASE_URL=...            # any OpenAI-compatible endpoint
export AI_API_KEY=...
export ARTIFICIAL_ANALYSIS_API_KEY=...   # optional; the desks degrade honestly without it

python -m runspace.workspace.serve workspace.yml
```

`workspace.yml` here carries placeholders only. Credentials live in the
environment.

That gives you the agents, the channels and the chat API. It does not run
`routines.yml` on a schedule: the workspace serves the routine definitions, but
firing them is the host application's job, and the site that hosts this demo is
not part of this repo. Trigger one by hand with
`POST /api/workspace/routines/<id>/run`.

## Tests

```bash
pytest tests/ -q
```

Offline, against fixtures — no key and no network needed. The cases that earn
their place are the ones that failed silently in production rather than loudly:
a sentinel price that survives arithmetic, a title that survives tag-stripping.
Each such test says in its docstring what broke.
