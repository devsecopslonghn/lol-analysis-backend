"""Local, read-only ROFL report extraction."""

from .rofl import ReplayParseError, parse_replay

__all__ = ["ReplayParseError", "parse_replay"]
