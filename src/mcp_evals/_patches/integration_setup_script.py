"""Run an integration-provided setup.sh in the sandbox before the agent runs.

Harbor's trial hooks (`TrialHookEvent`) don't expose `agent_environment`, so a
plain `Job.add_hook` can't exec into the sandbox. We patch `Trial._prepare` to
exec the registered script after env start + healthcheck + skill upload, just
before agent setup.

Use case: pre-authenticate CLI tools (e.g. `apify login --token "$APIFY_TOKEN"`)
so the agent doesn't burn a turn doing it itself - matching the implicit auth
that MCP integrations already get.
"""

from harbor.trial.trial import Trial

_SETUP_SCRIPT: str | None = None


def set_setup_script(script: str | None) -> None:
    global _SETUP_SCRIPT
    _SETUP_SCRIPT = script


_orig_prepare = Trial._prepare


async def _prepare_with_setup_script(self: Trial) -> None:
    await _orig_prepare(self)
    if _SETUP_SCRIPT:
        result = await self.agent_environment.exec(_SETUP_SCRIPT)
        if result.return_code != 0:
            raise RuntimeError(
                f"Integration setup script failed (exit {result.return_code}): "
                f"{result.stderr or result.stdout or '<no output>'}"
            )


Trial._prepare = _prepare_with_setup_script
