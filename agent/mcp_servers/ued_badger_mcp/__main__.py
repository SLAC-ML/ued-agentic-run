"""Stdio entry point: ``python -m ued_badger_mcp``.

Runs the ``ued_badger`` MCP server from the ued-agentic-run repo's
``bringup/`` (deployed on S3DF at ``UED_BRINGUP_DIR``). The server itself
never imports Badger: it validates and runs routines in the Badger venv
(``UED_BADGER_PYTHON``) as subprocesses. Only the simulator can be run;
routines for the real machine are drafted and checked read-only.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ.get(
    "UED_BRINGUP_DIR", "/sdf/group/mli/zhezhang/ued/agentic/bringup"))

from ued_badger.server import mcp  # noqa: E402

if __name__ == "__main__":
    mcp.run()
