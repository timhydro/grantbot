# GrantBot Pro Production Runbook

`grantbot_pro/` is the canonical GrantBot application. Historical installer and upgrade scripts remain in the repository only for migration/reference purposes; new development and operations should target the Python package under `grantbot_pro/grantbot/`.

## Supported runtime

- Python 3.10 through 3.13.
- FastAPI application: `grantbot.app:app`.
- CLI entrypoint: `grantbot` / `python -m grantbot`.
- Local AI provider: Ollama, configured through `.env`.
- Optional agent framework: CrewAI through the `agents` dependency extra, configured for local Ollama only.
- Primary bootstrap: `bash bootstrap.sh --with-local-ai`.
- Agent-enabled bootstrap: `bash bootstrap.sh --with-local-ai --with-agents`.
- Primary launcher: `bash run_grantbot.sh`.

## First installation

From the `grantbot_pro` directory:

```bash
cp -n .env.example .env
bash bootstrap.sh --with-local-ai
```

For the optional CrewAI agent layer:

```bash
bash bootstrap.sh --with-local-ai --with-agents
```

The bootstrap validates the Python version, creates `.venv`, installs dependencies, installs GrantBot in editable mode, compiles source and tests, initializes the database and canonical knowledge, runs the full pytest suite, checks the local AI provider, and prints complete system diagnostics.

CrewAI is not required for the deterministic GrantBot pipeline. The base product continues to operate if CrewAI is absent. When enabled, the v26 bridge uses CrewAI's Ollama provider form with the existing `OLLAMA_URL` and `OLLAMA_MODEL`; GrantBot does not configure hosted-model credentials for this path.

## Start the API

```bash
bash run_grantbot.sh
```

Default operator endpoints:

- `GET /` — service identity and version.
- `GET /health` — lightweight liveness check.
- `GET /docs` — interactive FastAPI documentation.
- `GET /master/health` — deeper GrantBot master-system health surface.
- `GET /v26/agents/health` — local agent roles, CrewAI availability, and Ollama status.
- `POST /v26/agents/discover` — mission-oriented live funding discovery using the existing v24 discovery engine.
- `POST /v26/agents/plan` — deterministic evidence/compliance/human-review execution plan.
- `POST /v26/agents/write-and-plan` — local Ollama narrative generation plus v25 quality gate and v26 execution planning.
- `POST /v26/agents/crew` — optional CrewAI multi-agent research/strategy/writing/review execution through local Ollama.

The launcher detects an existing GrantBot process through `/health` and refuses to silently collide with unrelated processes using the same port.

## Operator checks

```bash
.venv/bin/python -m grantbot --version
.venv/bin/python -m grantbot status
.venv/bin/python -m grantbot knowledge
.venv/bin/python -m pytest -q
```

## Canonical architecture

New code should integrate with the existing package instead of creating another installer-generation fork. The active system already includes funding discovery/connectors, eligibility, canonical knowledge, evidence, local-AI writing, NOFO analysis, matching, application orchestration, review staging, budgeting, compliance, risk intelligence, learning, packaging, document vault, command center, post-award services, and v26 agentic orchestration.

The v26 agent layer defines explicit responsibility boundaries for funding intelligence, eligibility/compliance, evidence research, strategy, persuasive narrative writing, quality review, and human-review routing. Deterministic GrantBot eligibility, evidence, quality, and human-control gates remain authoritative even when CrewAI is enabled.

Versioned module names such as `*_v21.py`, `*_v22.py`, `*_v23.py`, `*_v24.py`, and `*_v26.py` describe subsystem evolution; the deployable product version is the value exported by `grantbot.__version__` and declared in `pyproject.toml`.

## Legacy scripts

Do not use historical `install_v8.sh`, `install_v9.sh`, `v12_bootstrap.sh`, `grantbot_v13_v15_bundle.sh`, older upgrade scripts, or archived master installers as the starting point for new work. They are retained because they may contain migration history or recovery logic, but `bootstrap.sh`, `setup_local_ai.sh`, and `run_grantbot.sh` are the supported operational scripts.

## Release gate

A release is not considered certified until all of the following succeed on a clean supported Python environment:

```bash
python -m compileall -q grantbot tests
python -m pytest -q
python -m grantbot init
python -m grantbot status
```

After starting the API, verify:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

If local AI is enabled, `OllamaProvider().health()` must also report a usable provider/model before AI-generated grant drafting is treated as production-ready. If the optional agent layer is enabled, `/v26/agents/health` must report `installed: true` for CrewAI and an available local Ollama model before `/v26/agents/crew` is used.

## Safety boundary

GrantBot may research, score, draft, package, and stage funding applications. Human approval remains required for final submissions, certifications, attestations, banking actions, debt terms, collateral commitments, guarantees, match commitments, signatures, and other legally or financially binding actions. v26 agent outputs always return or imply `safe_to_submit=false`; agents cannot bypass this boundary.
