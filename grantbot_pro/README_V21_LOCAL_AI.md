# GrantBot Pro 21 — Free Local AI

GrantBot Pro 21 uses Ollama for local grant-writing generation. No paid AI API is required for the writer path.

## One-command setup

From the `grantbot_pro` directory:

```bash
bash bootstrap.sh --with-local-ai
```

This command creates the virtual environment, installs Python dependencies, installs GrantBot in editable mode, compiles the source, initializes the database, runs the complete test suite, installs/verifies Ollama when requested, pulls the configured local model if missing, verifies GrantBot can see the model, and runs diagnostics.

The default model is configured with:

```text
OLLAMA_MODEL=llama3.2:3b
```

You can change that value in `.env`. GrantBot can also use configured fallback models or another already-installed local Ollama model when fallback is enabled.

## Start GrantBot

```bash
bash run_grantbot.sh
```

The launcher detects the configured host and port, refuses to overwrite an unrelated process already using the port, and recognizes when GrantBot is already running.

## Local AI health

Authenticated API users with ADMIN, GRANT_WRITER, or REVIEWER roles can check:

```text
GET /v21/local-ai/health
```

The response reports the configured model, selected installed model, installed model list, context settings, and whether the local provider is available.

## Writer quality loop

The master writer evaluates each local-model draft through the GrantBot quality gate. If the draft fails, GrantBot can automatically request up to two corrective revisions from the local model. Revision prompts explicitly require removal of unsupported numeric claims, compliance with word limits, direct answers to the funder question, and factual grounding in the current evidence record.

Human review remains required before submission.
