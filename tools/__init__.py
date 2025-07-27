"""Helper tools for the HealthTrack agent."""

__all__ = ["tool_get_entries", "tool_summarize"]


def tool_get_entries(*args, **kwargs):
    from .get_entries import tool_get_entries as _impl
    return _impl(*args, **kwargs)


def tool_summarize(*args, **kwargs):
    from .summarize import tool_summarize as _impl
    return _impl(*args, **kwargs)
