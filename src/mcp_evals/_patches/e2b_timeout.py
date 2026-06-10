"""Clamp E2B sandbox `timeout` to 1 hour (free-tier limit).

Harbor hardcodes `timeout=86_400` (24 h) in
`harbor/src/harbor/environments/e2b.py:198`, which `AsyncSandbox.create`
rejects on the free plan. No constructor override is exposed.

Temporary: remove when harbor exposes a sandbox-timeout override, or when
we move to an E2B paid plan. Tracked in docs/todo.md.
"""

try:
    from e2b import AsyncSandbox
except ImportError:
    pass  # e2b extra not installed; nothing to patch
else:
    _MAX_TIMEOUT_SEC = 3600
    _orig_create = AsyncSandbox.create.__func__

    async def _create_with_clamped_timeout(cls, *args, **kwargs):
        if kwargs.get("timeout", 0) > _MAX_TIMEOUT_SEC:
            kwargs["timeout"] = _MAX_TIMEOUT_SEC
        return await _orig_create(cls, *args, **kwargs)

    AsyncSandbox.create = classmethod(_create_with_clamped_timeout)
