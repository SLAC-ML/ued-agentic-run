"""FastMCP server ``ued_beamline`` — a read-only view of the UED beamline.

Two tools, both read-only: ``ued_devices`` lists the device map and
``ued_snapshot`` reads the devices' PVs with Channel Access gets. Nothing
here can write a PV.

The device map (``ued_pvs.py``) and the reader (``snapshot.py``) live in the
ued-agentic-run repo's ``bringup/``, deployed on S3DF at ``UED_BRINGUP_DIR``,
so the map has one home. Launched over stdio by ``python -m ued_beamline``.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time

from fastmcp import FastMCP

BRINGUP = os.environ.get("UED_BRINGUP_DIR",
                         "/sdf/group/mli/zhezhang/ued/agentic/bringup")
sys.path.insert(0, BRINGUP)

# Over stdio, stdout IS the MCP channel. pyepics prints connection notices
# there, so every import and read that could touch it goes to stderr instead.
with contextlib.redirect_stdout(sys.stderr):
    from ued_pvs import CHANNELS  # noqa: E402
    from snapshot import read_all  # noqa: E402  (caget only)

GROUPS = sorted({c.group for c in CHANNELS})

mcp = FastMCP(
    "ued_beamline",
    instructions=(
        "Read-only view of the UED (ultrafast electron diffraction) beamline. "
        "ued_devices lists the mapped devices: each has a key, a group, the "
        "current PV, the PV the 2023 run-4 scripts used, and how sure the "
        "mapping is (CONFIRMED, LIKELY, CANDIDATE, UNMAPPED, or NO_ACCESS for "
        "accelerator PVs that ued-daq cannot reach). ued_snapshot reads their "
        "current values. Nothing here writes; this deployment never writes PVs."
    ),
)


@mcp.tool()
async def ued_devices(group: str = "") -> str:
    """List the UED devices this deployment knows, without reading any PV.

    Args:
        group: Optional group to filter by. One of: laser, sample, beamline,
            camera, gun_rf, magnets, correctors. Empty returns every device.

    Returns:
        JSON with ``groups`` (the valid group names) and ``devices``: one
        object per device with ``key``, ``group``, ``desc``, ``pv`` (current
        control PV, or null when unmapped), ``readback`` (the PVs a snapshot
        reads), ``old_pv`` (the 2023 run-4 PV), ``units``, ``status`` and
        ``note``.
    """
    if group and group not in GROUPS:
        return json.dumps({"error": f"unknown group {group!r}",
                           "groups": GROUPS})
    devices = [
        {"key": c.key, "group": c.group, "desc": c.desc, "pv": c.pv,
         "readback": list(c.readback), "old_pv": c.old_pv, "units": c.units,
         "status": c.status, "note": c.note}
        for c in CHANNELS if not group or c.group == group
    ]
    return json.dumps({"groups": GROUPS, "devices": devices})


@mcp.tool()
async def ued_snapshot(group: str = "") -> str:
    """Read the current values of the UED devices (Channel Access gets only).

    All PVs are read in parallel with a 2 s connection timeout, so a full
    snapshot takes a few seconds. Accelerator PVs (groups gun_rf, magnets,
    correctors) do not answer from ued-daq and come back not connected.

    Args:
        group: Optional group to read. One of: laser, sample, beamline,
            camera, gun_rf, magnets, correctors. Empty reads every device.

    Returns:
        JSON with ``time`` (local, when the read finished), ``connected`` and
        ``total`` counts, and ``channels``: one object per device with
        ``key``, ``group``, ``desc``, ``pv``, ``status``, ``units``,
        ``readback`` (PV name to value; null when the PV did not answer) and
        ``connected``.
    """
    if group and group not in GROUPS:
        return json.dumps({"error": f"unknown group {group!r}",
                           "groups": GROUPS})
    with contextlib.redirect_stdout(sys.stderr):
        rows = read_all()
    if group:
        rows = [r for r in rows if r["group"] == group]
    for r in rows:
        r.pop("old_pv", None)
        r.pop("note", None)
    return json.dumps({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "connected": sum(r["connected"] for r in rows),
        "total": len(rows),
        "channels": rows,
    }, default=str)
