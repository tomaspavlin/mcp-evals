# Python CLI migration

Move from `harbor run -c configs/*.yaml` to a thin Python CLI built on Harbor's `Job` API. Unlocks codex agent overrides, shared environment defaults, and an `integrations/` abstraction that bundles the (MCP servers | skills | instruction append | EVAL_VARIANT) tuple.

## Why

Today every yaml in `configs/` repeats `environment.type`, `n_concurrent_trials`, agent kwargs, and spreads the variant signal across three places (`extra_instruction_paths`, `agents[].mcp_servers`, `verifier.env.EVAL_VARIANT`). Python gives us composition, hooks, and `BaseAgent` subclasses; yaml stays for data (integrations, base config) so it's still grep-able.

## Scope (this migration)

- New `src/mcp_evals/` package + `pyproject.toml`, console script `mcp-evals run`.
- One integration directory: `integrations/apify-mcp/` (yaml + instruction).
- Migrate one config: `apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` (single task + single agent → fastest end-to-end test).
- Leave the other 21 yamls and `scripts/run.sh` as legacy/reference. To be removed later.
- **Out of scope**: codex override (planned), other integrations, sweeps, proxy script centralization (see `docs/todo.md`).

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
├── pyproject.toml              # NEW — src layout, uv_build, [project.scripts] mcp-evals = "mcp_evals.cli.main:app"
├── src/mcp_evals/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py             # Typer app
│   │   └── run.py              # `mcp-evals run …`
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── model.py            # Integration Pydantic model
│   │   └── loader.py           # load_integration(name) -> Integration
│   ├── job_builder.py          # build_job_config(integration, base, overrides) -> JobConfig
│   └── defaults.py             # DEFAULT_ENVIRONMENT, DEFAULT_AGENT_KWARGS, N_CONCURRENT
├── integrations/               # NEW — one directory per integration
│   └── apify-mcp/
│       ├── integration.yaml    # name, eval_variant, mcp_servers, skills
│       └── instruction.md      # appended to every task's instruction
├── configs/                    # existing yamls kept as reference
├── instructions/, tasks/, skills/, apps/, docs/, scripts/, jobs/   # unchanged
└── scripts/run.sh              # KEEP for legacy
```

`agents/` subpackage will be added under `src/mcp_evals/` when the codex override lands. Reference: `harbor/examples/agents/marker_agent.py` for the `BaseAgent` subclass pattern.

## Integration directory shape

```
integrations/apify-mcp/
├── integration.yaml
└── instruction.md       # auto-discovered alongside integration.yaml
```

```yaml
# integrations/apify-mcp/integration.yaml
name: apify-mcp
eval_variant: mcp
mcp_servers:
  - name: apify
    transport: stdio
    command: /usr/local/bin/apify-mcp-proxy
    args: []
skills: []
```

The `Integration` model fans `mcp_servers` and `skills` into every agent at job-build time, appends `instruction.md` via `extra_instruction_paths`, and sets `verifier.env["EVAL_VARIANT"]`.

Note on `command: /usr/local/bin/apify-mcp-proxy` — that path is **inside the container**. Each task's `environment/Dockerfile` `COPY`s the proxy script there. Today the script is duplicated across each task's `environment/` dir; centralizing via a shared docker base image is feasible but deferred (see `docs/todo.md`).

## Config shape (our schema, not harbor's JobConfig)

`-c` now points at our own thin schema. Loader expands it into a harbor `JobConfig` at runtime by merging the named integration + `defaults.py`.

```yaml
# configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml (new shape)
job_name: apify-fetch-actor-id-opencode-deepseek-mcp-eval
integration: apify-mcp
tasks:
  - path: tasks/apify-fetch-actor-id
agents:
  - name: opencode
    model_name: openrouter/deepseek/deepseek-chat-v3.1
```

Everything else (`n_concurrent_trials`, `environment`, agent `kwargs`, `mcp_servers`, `extra_instruction_paths`, `EVAL_VARIANT`) comes from the integration + defaults. Per-config overrides allowed via `agents[].kwargs`, top-level `n_concurrent_trials`, etc.

## CLI surface

```
mcp-evals run -c configs/<name>.yaml \
              [--integration NAME] [--job-name NAME] [-y] [--n-attempts N] [--n-concurrent N] [--env-file PATH]
```

`--integration` overrides what's in the yaml. `-c` is optional once defaults + flags cover the common case — for now most runs pass it. Same `.env` loading and `-y` auto-confirm semantics as `scripts/run.sh` today.

## Migration target

`configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` — single task, single agent → fast end-to-end smoke. After migration, `mcp-evals run -c configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` should produce the same `JobConfig` as the legacy yaml did via `harbor run`.
