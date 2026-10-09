"""Stdio entry point: ``python -m ued_beamline``."""

from __future__ import annotations

from .server import mcp

if __name__ == "__main__":
    mcp.run()
