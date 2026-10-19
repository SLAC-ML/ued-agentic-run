"""Stdio entry point: ``python -m ued_tuning_mcp``.

Runs the ``ued_tuning`` MCP server from the ued-agentic-run repo's
``bringup/`` (deployed on S3DF at ``UED_BRINGUP_DIR``), so the stage code has
one home. The backend is forced to ``epics``: this deployment never drives
the simulator, and the EPICS backend reads with caget and refuses every
write before any EPICS call, so each stage tool stops at its first write.
"""

from __future__ import annotations

import os
import sys

# Set before the import: server.py picks its backend when it loads.
os.environ["UED_TUNING_BACKEND"] = "epics"
sys.path.insert(0, os.environ.get(
    "UED_BRINGUP_DIR", "/sdf/group/mli/zhezhang/ued/agentic/bringup"))

from ued_tuning.server import mcp  # noqa: E402

if __name__ == "__main__":
    mcp.run()
