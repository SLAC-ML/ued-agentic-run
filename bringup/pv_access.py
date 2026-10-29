"""How the UED tools name PVs on the wire.

The maps (ued_pvs.py, ued_tuning/channels.py) hold each PV's own name. From
S3DF the PVs are reached through the EPICS gateway 172.24.3.10:5110, which
serves the hutch PVs (UED:*) under their own names but the accelerator-side
PVs only under a prefix (e.g. UED:USER:SIOC:AS01:KY03:0:AREQ). So every read
goes through wire_name(), which adds the prefix when one is configured:

  UED_ACCEL_PV_PREFIX   prefix for every PV that doesn't start with one of
                        UED_HUTCH_PV_PREFIXES (default: none, names as-is)
  UED_HUTCH_PV_PREFIXES comma-separated name starts served as-is
                        (default: "UED:")

On ued-daq (direct Channel Access) leave the prefix unset.

A prefixed name can answer without being live: on 2026-10-29 the gateway
served UED:USER:SIOC:AS01:KY03:0:AREQ, SOLN BCTRL and the gun temperature
as 0.0, never processed (UDF, timestamp the EPICS epoch, 1990-01-01). Such
a value is not the machine's; readers check never_processed() and treat it
as unavailable.
"""
from __future__ import annotations

import os


def accel_prefix() -> str:
    return os.environ.get('UED_ACCEL_PV_PREFIX', '')


def hutch_prefixes() -> tuple:
    raw = os.environ.get('UED_HUTCH_PV_PREFIXES', 'UED:')
    return tuple(p.strip() for p in raw.split(',') if p.strip())


EPICS_EPOCH = 631152000.0       # 1990-01-01 00:00 UTC, as a POSIX time


def never_processed(timestamp) -> bool:
    """True for a record that holds no value yet: its timestamp is the
    EPICS epoch."""
    return timestamp is not None and float(timestamp) <= EPICS_EPOCH + 1.0


def prefixed(pv: str) -> bool:
    """Whether wire_name() adds the gateway prefix to this PV."""
    return wire_name(pv) != pv


def wire_name(pv: str) -> str:
    """The name to send over Channel Access for a map PV name."""
    prefix = accel_prefix()
    if not prefix or pv.startswith(prefix) or pv.startswith(hutch_prefixes()):
        return pv
    return prefix + pv


def describe() -> dict:
    """The current settings, for tools that report how they reach PVs."""
    return {'ca_addr_list': os.environ.get('EPICS_CA_ADDR_LIST'),
            'ca_auto_addr_list': os.environ.get('EPICS_CA_AUTO_ADDR_LIST'),
            'accel_pv_prefix': accel_prefix() or None,
            'hutch_pv_prefixes': list(hutch_prefixes())}
