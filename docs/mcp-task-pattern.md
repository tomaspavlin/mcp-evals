# Task pattern: apps and connectors

How we wire auth'd remote MCPs, CLIs, and skills into a Harbor task. The same task dir backs every connector - the tool choice lives in the job config, not `task.toml`. Tasks can compose multiple apps (e.g. Apify + GitHub) in a single trial.

## The auth blocker

Harbor's `MCPServerConfig` accepts `name | transport | url | command | args`. **No `headers`, no `env`.** Unsupported fields are dropped on purpose. So you cannot declare an `Authorization: Bearer <TOKEN>` remote MCP. Confirmed against `src/harbor/models/task/config.py` + PR #1675.

## The workaround: stdio wrapper

- Declare a stdio MCP whose `command` is a wrapper script baked into the shared base image.
- Wrapper runs `mcp-remote` (npm proxy), which speaks stdio locally and forwards to the remote streamable-http endpoint with an injected `Authorization` header.
- Token reaches the container via `environment_env` on the cell, materialized into `[environment.env]` at job build time, which IS supported by Harbor and forwards from host `os.environ`.

## File layout

```
tasks/<name>/
  task.toml                  # per-task timeouts + [connector_evals].apps = [...]
  instruction.md             # task only - no mention of connector
  environment/               # gitignored; materialized from images/base/ on `connector-evals run`
  tests/
    test.sh, check.py        # Reward Kit verifier (see below)
  solution/solve.sh

apps/<app>/<connector>/
  cell.yaml                  # mcp_servers, environment_env, setup_env, verifier_env
  instruction.md             # auto-discovered, appended via extra_instruction_paths
  setup.sh                   # optional; exec'd in the sandbox after env start, before
                             # the agent. Use for pre-auth (e.g. `apify login`).
  teardown.sh                # optional; runs after the agent, before artifact collection.
  skills/<name>/SKILL.md     # optional, auto-discovered (skill connector)

images/base/
  Dockerfile                 # node:22-bookworm + every CLI + mcp-remote + mcpc + proxies
  apify-mcp-proxy.sh         # one wrapper per app, all pre-installed
  github-mcp-proxy.sh

configs/
  <task>-<harness>-<model>-<connector>-eval.yaml   # RunConfig: connector: <name>
```

The materialize step (`connector-evals run` does it automatically; `connector-evals materialize` exposes it standalone) copies `images/base/` into each target task's `environment/` dir before harbor sees the task. The Dockerfile is identical across all runs, so the sandbox template cache stays hot. Per-task env dirs are gitignored - `images/base/` is the source of truth.

## task.toml snippet

Per-task overrides (timeouts, optional verifier env) plus a `[connector_evals]` block listing which apps the task needs. No `[[environment.mcp_servers]]`, no token passthrough - those are hoisted to the cell / `defaults.py`.

```toml
version = "1.0"

[connector_evals]
apps = ["apify"]                  # or ["apify", "github"] for cross-app

[verifier]
timeout_sec = 60.0

[agent]
timeout_sec = 180.0
```

Token passthrough lives on the cell:

```yaml
# apps/apify/mcp/cell.yaml
environment_env:
  APIFY_TOKEN: ${APIFY_TOKEN}        # resolved against host env at job build time
```

## Cell: pick the connector for one app

A cell decides how one app is exposed for one connector. `instruction.md` in the task stays connector-agnostic; the cell's `instruction.md` tells the agent which tool to use. The RunConfig picks `connector:` (one value applied to every app the task declares) or `app_connectors:` (per-app map for hybrid runs).

MCP cell (`apps/apify/mcp/cell.yaml`):

```yaml
mcp_servers:
  - name: apify
    transport: stdio
    command: /usr/local/bin/apify-mcp-proxy
    args: []
environment_env:
  APIFY_TOKEN: ${APIFY_TOKEN}
```

Skill cell (Harbor uploads the host dir into `/harbor/skills/<name>/` at trial start, then copies into each harness's skill dir: `~/.claude/skills/`, `~/.config/opencode/skills/`, `$HOME/.agents/skills/` for claude-code, opencode, codex respectively):

```yaml
# apps/apify/skill/cell.yaml
mcp_servers: []
# skills/<name>/SKILL.md under the cell dir is auto-discovered
# skill is just instructions to use the apify CLI, so the connector the
# verifier sees is the same as the cli cell.
setup_env:
  APIFY_TOKEN: ${APIFY_TOKEN}
```

`job_builder` resolves `(apps, connector | app_connectors)` against `task.toml`, fans the matched cells' `mcp_servers` and `skills` into every agent, and appends each cell's `instruction.md` via the job-level `extra_instruction_paths` field. Each instruction file is appended to the task's `instruction.md` with `\n\n` separators (`src/harbor/models/task/task.py:181`).

Harbor merges `task.config.environment.mcp_servers` with `agent.mcp_servers` by name (last wins). There's no way to disable a task-level MCP from the yaml, which is why the task no longer declares one. See `src/harbor/trial/trial.py:641`.

## Wrapper template

```bash
#!/bin/bash
# Stdio shim for https://mcp.apify.com/. Harbor's MCPServerConfig has no
# `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
set -eu
: "${APIFY_TOKEN:?APIFY_TOKEN env var is required}"
mcp-remote https://mcp.apify.com/ --header "Authorization: Bearer $APIFY_TOKEN" \
  2> >(sed -E "s/apify_api_[A-Za-z0-9]+/apify_api_REDACTED/g" >&2)
```

The `sed` is not cosmetic. `mcp-remote` logs the raw `Authorization` header to stderr on startup; that stream is captured by claude-code and persisted to `jobs/.../trajectory.json`. We had two token leaks before adding the filter. Match the regex to whatever token format the vendor uses.

## Sandbox choice

`--env docker` only, today. **Daytona's free/Hobby tiers enforce an outbound allowlist** that doesn't include `*.apify.com` (and likely won't include `*.linear.app`, `*.notion.com`). Symptom: TLS handshake stalls, MCP "failed", curl returns empty body. Tier 3 ($500 top-up) gets full internet, or email `support@daytona.io` to add a domain. See `docs/harbor-constraints.md` for details.

## Verifier design rule

**The expected answer must require an actual tool call**, not a name the agent can guess from the prompt. We tried a "list connected MCP names → /app/mcps.txt" task and the agent passed by writing `apify\n` from the init message alone, with `connected: []`. Use a stable opaque value the API returns (e.g., `moJRLRc85AitArpNN` for `apify/web-scraper`).

## Verifier pattern (Reward Kit)

`tests/test.sh` is a one-liner that runs [Reward Kit](https://www.harborframework.com/docs/rewardkit); it discovers criteria in `/tests/`, evaluates them against the workspace at `/app`, and writes `/logs/verifier/reward.json`. No pytest, no manual reward file. The verifier reads the per-app connector map from `CONNECTOR_EVALS_CONNECTORS_JSON` (primary), `CONNECTOR_EVALS_CONNECTOR` (shorthand when one connector applies to all), and `CONNECTOR_EVALS_APPS` (csv of app names).

```bash
# tests/test.sh
#!/bin/bash
set -e
curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh
source $HOME/.local/bin/env
uvx --from harbor-rewardkit==0.1.4 rewardkit /tests
```

Built-in helper (substring/existence check, permissive):
```python
# tests/check.py
import rewardkit as rk
rk.file_contains("mcps.txt", "apify")
```

Custom criterion (exact match, strict — use when a built-in would be too permissive):
```python
# tests/check.py
from pathlib import Path
from rewardkit import criterion

@criterion
def actor_id_matches(workspace: Path) -> bool:
    return (workspace / "actor_id.txt").read_text().strip() == "moJRLRc85AitArpNN"
```

## Adapt for another app

1. Copy `tasks/apify-fetch-actor-id/` to `tasks/<app>-<task>/` (drop the `environment/` dir - it's now owned by `images/base/`).
2. Rewrite `instruction.md` (task only, no connector wording) and `tests/check.py` for the new app. Set `[connector_evals].apps = ["<app>"]` in `task.toml`.
3. In `.env.example` + `.env`: add the new token.
4. Create `apps/<app>/<connector>/` cells (one per connector you support) with `cell.yaml` (`mcp_servers` and/or `setup_env`, `environment_env`) and `instruction.md` (connector wording). If a new MCP proxy is needed, drop a `<app>-mcp-proxy.sh` into `images/base/` and install it from the Dockerfile.
5. Add a RunConfig under `configs/` with `connector: <name>` and `tasks: - path: tasks/<app>-<task>`. See `configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` for the canonical example.

## Existing tasks

- `tasks/apify-fetch-actor-id/` - real Apify call, not gameable. All four connectors (mcp/cli/mcpc/skill) wired.
- `tasks/apify-scrape-page/` - runs an Actor and reads its dataset. All four connectors wired.
- `tasks/apify-mcp-connected/` - connection smoke, gameable. MCP-only (no skill/cli equivalent makes sense).
- `tasks/cross-actor-meta-and-repo-meta/` - cross-app: looks up an Apify Actor and a GitHub repo in one trial; declares `apps = ["apify", "github"]` and can mix connectors via `app_connectors:`.
