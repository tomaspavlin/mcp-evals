"""Run an integration-provided teardown.sh in the agent sandbox after the
agent finishes but before artifacts are collected.

Symmetric to integration_setup_script.py: that one runs in `Trial._prepare`
just before agent setup; this one wedges into `SingleStepTrial._collect_artifacts`
so the agent's working tree can be post-processed (build, lint, snapshot, ...)
and the outputs land in the artifacts dir before the verifier sees them.

Unlike setup, a non-zero teardown exit is logged and swallowed, not raised.
The verifier often wants a failed post-process (build error, lint failure)
as real signal to grade against, not as a trial abort.

Recovery path (`_recover_outputs` -> `_collect_artifacts`) is naturally guarded
by `_are_artifacts_collected`: the second call short-circuits before we get
a chance to re-run teardown, so a recovery doesn't double-run.

Scope note: only patches `SingleStepTrial`. Fine while every trial type we
use is single-step; revisit if a multi-step trial type appears.
"""

from harbor.trial.single_step import SingleStepTrial

_TEARDOWN_SCRIPT: str | None = None
_TEARDOWN_ENV: dict[str, str] = {}


def set_teardown_script(script: str | None, env: dict[str, str] | None = None) -> None:
    global _TEARDOWN_SCRIPT, _TEARDOWN_ENV
    _TEARDOWN_SCRIPT = script
    _TEARDOWN_ENV = dict(env or {})


_orig_collect_artifacts = SingleStepTrial._collect_artifacts


async def _collect_artifacts_with_teardown(self: SingleStepTrial) -> None:
    if not self._are_artifacts_collected and _TEARDOWN_SCRIPT:
        try:
            result = await self.agent_environment.exec(
                _TEARDOWN_SCRIPT, env=_TEARDOWN_ENV or None
            )
            if result.return_code != 0:
                tail = (result.stderr or result.stdout or "<no output>")[-500:]
                self.logger.warning(
                    f"Integration teardown script exited {result.return_code}: {tail}"
                )
        except Exception as exc:
            # Don't let a teardown crash prevent artifact collection.
            self.logger.warning(f"Integration teardown script raised: {exc}")
    await _orig_collect_artifacts(self)


SingleStepTrial._collect_artifacts = _collect_artifacts_with_teardown
