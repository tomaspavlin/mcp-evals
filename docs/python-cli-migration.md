# Python CLI design

`mcp-evals run` (in `src/mcp_evals/`) is a thin Python CLI built on Harbor's `Job` API. It expands our own `RunConfig` schema + a named `Integration` + Python defaults into a harbor `JobConfig`, then calls `await Job.create(config); await job.run()`. Replaces the previous `harbor run -c configs/*.yaml` flow.

## Why a custom layer

Harbor's `JobConfig` yaml repeats `environment.type`, `n_concurrent_trials`, agent kwargs in every file and spreads the tool-variant signal across three places (`extra_instruction_paths`, `agents[].mcp_servers`, `verifier.env.EVAL_VARIANT`). The Python layer gives us composition (the `integration:` field), hooks, and a hook-point for `BaseAgent` subclasses (e.g. future codex override). Yaml stays for data so configs remain grep-able.

## Decisions

| | Choice | Why |
|---|---|---|
| CLI strategy | Independent Typer app mirroring harbor flag names (`-c`, `--job-name`, `-y`, `--n-attempts`, `--n-concurrent`, `--env-file`) + our `--integration` | Looks like pass-through to users without coupling to harbor CLI internals. Keeps Python entrypoint for hooks/agent overrides. |
| Yaml parsing | Reuse `JobConfig.model_validate(yaml.safe_load(...))` from harbor verbatim | No wheel-reinvention. Same for our `Integration` and `RunConfig` Pydantic models. |
| Config schema | **Our own** thin schema (`RunConfig`), expanded to harbor `JobConfig` at runtime | Lets `integration:` field replace the per-config duplication of env / mcp_servers / instructions / EVAL_VARIANT. |
| Layout | `src/mcp_evals/`, top-level `integrations/` (data, not under `examples/`) | mcp-evals is an internal project, not a library — `examples/` would be cargo-cult. |
| Build backend | `uv_build` | Match harbor. |
| Defaults | Python (`defaults.py`) — env, n_concurrent, agent kwargs | Simpler than a base yaml; integrations can still override per-field. |
| Overlay precedence | CLI flags > integration yaml > base config yaml > `defaults.py` | Matches harbor's CLI override behavior. |

## Directory layout

```
mcp-evals/
├── pyproject.toml              # src layout, uv_build, [project.scripts] mcp-evals = "mcp_evals.cli.main:app"
├── src/mcp_evals/
│   ├── cli/main.py             # Typer app
│   ├── cli/run.py              # `mcp-evals run …`
│   ├── integrations/model.py   # Integration Pydantic model
│   ├── integrations/loader.py  # load_integration(name) -> Integration
│   ├── config.py               # RunConfig schema + load_run_config()
│   ├── job_builder.py          # build_job_config(run, integration) -> JobConfig
│   └── defaults.py             # DEFAULT_ENVIRONMENT, DEFAULT_AGENT_KWARGS, DEFAULT_N_CONCURRENT_TRIALS
├── integrations/<name>/        # one directory per integration
│   ├── integration.yaml        # name, eval_variant, mcp_servers, skills
│   └── instruction.md          # appended to every task's instruction (auto-discovered)
├── configs/<name>.yaml         # RunConfig schema
```

`agents/` subpackage will be added under `src/mcp_evals/` when the codex override lands. Reference: `harbor/examples/agents/marker_agent.py` for the `BaseAgent` subclass pattern.

## Integration shape

```yaml
# integrations/apify-mcp/integration.yaml
name: apify-mcp
eval_variant: mcp
mcp_servers:
  - name: apify
    transport: stdio
    command: /usr/local/bin/apify-mcp-proxy   # path inside the container
    args: []
skills: []
```

The `Integration` model fans `mcp_servers` and `skills` into every agent at job-build time, appends `instruction.md` via `extra_instruction_paths`, and sets `verifier.env["EVAL_VARIANT"]`.

Note on `command: /usr/local/bin/apify-mcp-proxy` — that path resolves **inside the container**. Each task's `environment/Dockerfile` `COPY`s the proxy script there. Today the script is duplicated across each task's `environment/`; centralizing via a shared docker base image is feasible but deferred (see `docs/todo.md`).

## RunConfig shape

```yaml
# configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml
job_name: apify-fetch-actor-id-opencode-deepseek-mcp-eval
integration: apify-mcp
tasks:
  - path: tasks/apify-fetch-actor-id
agents:
  - name: opencode
    model_name: openrouter/deepseek/deepseek-chat-v3.1
```

Everything else (`n_concurrent_trials`, `environment`, agent `kwargs`, `mcp_servers`, `extra_instruction_paths`, `EVAL_VARIANT`) comes from the integration + defaults. Per-config overrides allowed via `agents[].kwargs`, top-level `n_concurrent_trials`, `n_attempts`.

## CLI

```
mcp-evals run -c configs/<name>.yaml \
              [--integration NAME] [--job-name NAME] [-y] [--n-attempts N] [--n-concurrent N] [--env-file PATH]
```

`--integration` overrides what's in the yaml. `.env` is auto-loaded from cwd. `-y` skips the host-env-access confirmation.
