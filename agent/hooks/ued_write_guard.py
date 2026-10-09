#!/usr/bin/env python3
"""
---
name: UED Write Guard
description: Refuses any tool call that would put a PV value on ued-daq
summary: Blocks caput/pvput and EPICS put calls in shell commands, file writes and python
event: PreToolUse
tools: Bash, Write, Edit, MultiEdit, NotebookEdit, python
safety_layer: 1
---
## Why
UED rule: the agent never writes PVs. ued-daq sits on the hutch network and
can reach every hutch IOC with write access, so the guard cannot live in
Channel Access; it lives here, ahead of the permission rules.

## What it refuses
Every string in the call's `tool_input` is scanned (a shell command, a file's
new content, an edit, a notebook cell, python sent to the executor), so an
EPICS put is caught whether it is typed into the shell or written into a
script first. The patterns are the command-line clients (`caput`, `pvput`)
and the python put calls (`epics.caput`, `ca.put`, `PV(...).put(...)`).

`.put(` also matches unrelated code (a queue, an HTTP PUT). That is accepted
on a production host: a refused harmless call costs a retry, a missed put
costs a beam.

Exit code 2 blocks the call before Claude Code evaluates any permission rule;
the reason goes to stderr, which Claude Code shows the model. A call that
cannot be parsed is refused too (fail closed).
"""
import json
import re
import sys

PUT = re.compile(
    r"\bcaput\b|\bpvput\b|\bca_?put\b|\bca\.put\b|\.put\s*\(",
    re.IGNORECASE,
)


def strings(value):
    """Every string inside a JSON value, depth first."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def main():
    try:
        call = json.load(sys.stdin)
    except Exception as exc:
        print(f"UED write guard: could not read the tool call ({exc}); "
              "refusing it.", file=sys.stderr)
        return 2
    tool = call.get("tool_name", "?")
    for text in strings(call.get("tool_input", {})):
        m = PUT.search(text)
        if m:
            print(f"UED write guard: refused {tool}. It contains "
                  f"{m.group(0)!r}, an EPICS put. This deployment is "
                  "read-only on ued-daq: read PVs with caget or the "
                  "ued_beamline tools, and leave every write to the operator.",
                  file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
