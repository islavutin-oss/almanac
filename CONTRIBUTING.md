# Contributing

This is the agent half of a live demo: the SOULs, tools, routines and workspace
config behind [almanac.agentino.co](https://almanac.agentino.co). The site
itself is closed; everything that decides what the agents *do* is here.

## Getting it running

```bash
pip install "runspace[agentino,workspace,server]"
export AI_BASE_URL=... AI_API_KEY=...
python -m runspace.workspace.serve workspace.yml
```

`ARTIFICIAL_ANALYSIS_API_KEY` is optional and free. Without it the desks lose
quality and latency figures and say so, rather than reporting a blank as a zero.

## Before you open a pull request

```bash
pytest tests/ -q
ruff check .
ruff format --check .
```

All three are what CI runs, and CI is the gate. The suite is offline against
fixtures, so it needs no key and no network.

## What a good change looks like

**Prompt changes are behaviour changes.** A SOUL edit has no test that fails
when it is wrong, so say in the pull request what you asked, what the agent did
before, and what it does now. "Reads better" is not a reason.

**Add a test when a bug was silent.** The suite is not here for coverage. It is
here for the failures that produced plausible-looking output instead of an
error — a sentinel value that survives arithmetic, a title that survives
tag-stripping. If the bug you fixed would have shipped unnoticed, it needs a
test; put what broke in the docstring.

**Numbers need a source.** No hardcoded model counts, prices or benchmark
figures in prose or docstrings. They drift, and a stale number is worse than no
number because it still looks authoritative.

**Say what is unmeasured.** Missing data is reported as missing. A model with no
published latency is not a fast model, and nothing here may render it as one.

## What does not belong here

- Credentials, or anything that identifies the inference provider behind
  `AI_BASE_URL`. `workspace.yml` carries placeholders and reads the environment.
- Anything that collects or stores a visitor's contact details.
- Site code, deployment scripts, or infrastructure — different repo, closed.

## Layout

```
agents/_*.py, agents/_*/    shared across desks: catalogue, feeds, history
agents/<desk>/SOUL.md       what the agent is
agents/<desk>/tools/        what it can do
agents/_scope.md            the shared scope guard, included by every SOUL
routines.yml                what runs unattended, and when
workspace.yml               the workspace: agents, channels, settings
```

## Licence

Apache-2.0, the same as [runspace](https://github.com/islavutin-oss/runspace)
and [agentino](https://github.com/islavutin-oss/agentino). By opening a pull
request you agree your contribution is licensed under it.
