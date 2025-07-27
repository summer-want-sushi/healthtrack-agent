"""Helper tools for the HealthTrack agent."""

__all__ = ["tool_get_entries"]


def tool_get_entries(*args, **kwargs):
    from .get_entries import tool_get_entries as _impl
    return _impl(*args, **kwargs)
