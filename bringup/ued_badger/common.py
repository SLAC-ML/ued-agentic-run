"""Shared pieces of the agent-friendly Badger for UED.

Two Python environments meet here. The MCP server (server.py) runs in the
UED agent's environment and never imports Badger. Validation (validate.py)
and runs (runner.py) run in the Badger environment, $UED_BADGER_PYTHON (the
AgenticOpt venv with the Badger fork and Xopt 3.1), as subprocesses.

Knobs and observables use the ued_tuning logical names (sol1, xc00, ...,
andor_spot_size_px), so one routine runs on both environments:
  ued_sim  the virtual UED (GPT + analytic models), for rehearsal
  ued      the real machine through the EPICS backend, read-only for now
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BRINGUP = Path(__file__).resolve().parents[1]
REPO_SIM = BRINGUP.parent / 'sim'
ROOT = Path(os.environ.get('UED_BADGER_ROOT',
                           '/sdf/group/mli/zhezhang/ued/agentic/badger'))
PLUGIN_ROOT = Path(os.environ.get('UED_BADGER_PLUGIN_ROOT',
                                  BRINGUP / 'ued_badger' / 'plugins'))
ARCHIVE_ROOT = ROOT / 'archive'
ROUTINES_DIR = ROOT / 'routines'
RUNS_DIR = ROOT / 'runs'
SIM_STATE = ROOT / 'ued_sim_state.json'     # preset stage5; others add _<preset>
BADGER_PYTHON = os.environ.get(
    'UED_BADGER_PYTHON', '/sdf/group/mli/zhezhang/AgenticOpt/.venv/bin/python')

# The knobs: the post-collimator co-tuning (procedure 5: solenoids and
# correctors; XC/YC04 keep the beam near the Andor centre) and the sample
# position (procedure 7). A knob is offered only where the setup file gives
# it a safety range. And what the Andor gives back: the spot (5) and the
# whole-frame diffraction intensity (7).
MAGNET_KNOBS = ('sol1', 'sol2', 'xc00', 'yc00', 'xc01', 'yc01', 'xc02',
                'yc02', 'xc04', 'yc04')
SAMPLE_KNOBS = ('sample_x', 'sample_y')
KNOBS = MAGNET_KNOBS + SAMPLE_KNOBS
OBSERVABLES = ('andor_spot_size_px', 'andor_total',
               'andor_offset_from_centre_px', 'andor_sigma_x_px',
               'andor_sigma_y_px', 'andor_saturated', 'andor_frame_sum')
ENVIRONMENTS = {
    'ued_sim': 'The virtual UED (GPT beam transport, analytic models), set '
               'up as after stage 5 (preset stage5) or at the Bi sample with '
               'the main beam in the Andor through hole (preset stage7). '
               'Rehearsal only.',
    'ued': 'The real UED through EPICS. Read-only for the agent. Writes '
           'only in an operator\'s Badger on ued-daq, started by '
           'scripts/badger_ued.sh, and only to the knobs, inside the setup '
           'file\'s safety ranges.',
}
# Set by scripts/badger_ued.sh, never by the agent's servers: lets the `ued`
# environment write its knobs. UED_BADGER_DRY_RUN=1 logs the writes instead.
ALLOW_WRITES_ENV = 'UED_BADGER_ALLOW_WRITES'
DRY_RUN_ENV = 'UED_BADGER_DRY_RUN'
WRITE_LOG = ROOT / 'ued_writes.jsonl'


def sim_setup_path() -> Path:
    return Path(os.environ.get('UED_SIM_SETUP_FILE',
                               REPO_SIM / 'ued_setup_sim.yaml'))


def setup_file(env_name: str) -> Path:
    """The setup file whose safety ranges bound this environment's knobs."""
    if env_name == 'ued_sim':
        return sim_setup_path()
    sys.path.insert(0, str(BRINGUP))
    import ued_automation as auto
    return auto.setup_path()


def setup_for(env_name: str) -> dict:
    import yaml
    with open(setup_file(env_name)) as f:
        return yaml.safe_load(f) or {}


def knob_bounds(env_name: str) -> dict:
    """{knob: [lo, hi]} from the environment's safety ranges."""
    limits = setup_for(env_name).get('limits') or {}
    return {k: [float(limits[k][0]), float(limits[k][1])]
            for k in KNOBS if limits.get(k) is not None}


def init_badger_settings() -> str:
    """Point Badger at the UED plugin and archive roots (Badger env only).

    Badger reads its settings when badger.factory is imported, so this runs
    before any other badger import. Returns the settings file path."""
    import yaml
    for d in (ARCHIVE_ROOT, ROOT / 'tmp'):
        d.mkdir(parents=True, exist_ok=True)

    def entry(value, name):
        return {'value': str(value), 'is_path': True, 'display_name': name,
                'description': f'UED agentic Badger: {name}'}
    settings = {
        'BADGER_PLUGIN_ROOT': entry(PLUGIN_ROOT, 'plugin root'),
        'BADGER_ARCHIVE_ROOT': entry(ARCHIVE_ROOT, 'archive root'),
        'BADGER_LOGBOOK_ROOT': entry(ROOT / 'tmp' / 'logbook', 'logbook root'),
        'BADGER_TEMPLATE_ROOT': entry(ROOT / 'tmp' / 'templates',
                                      'template root'),
        'BADGER_DB_ROOT': entry(ROOT / 'tmp' / 'db', 'db root'),
        'BADGER_LOG_DIRECTORY': entry(ROOT / 'tmp' / 'logs', 'log directory'),
    }
    for k in ('BADGER_LOGBOOK_ROOT', 'BADGER_TEMPLATE_ROOT', 'BADGER_DB_ROOT',
              'BADGER_LOG_DIRECTORY'):
        Path(settings[k]['value']).mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix='ued-badger-', suffix='.yaml')
    with os.fdopen(fd, 'w') as f:
        yaml.safe_dump(settings, f)
    from badger.settings import init_settings
    init_settings(path)
    return path
