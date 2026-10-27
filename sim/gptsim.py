"""Run the UED bring-up deck (ued_bringup.in) with GPT; read screen stats.

Meant to run on S3DF (iana or a Slurm node) after
    source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh

    from gptsim import run, scan
    df = run({'xc00': 0.5, 'x0': 20e-6})          # one simulation
    dfs = scan([{'xc00': k} for k in kicks])      # many, in parallel

Each call returns a DataFrame with one row per screen (z in m), holding
beam centroid [um], angle [mrad], rms size [um], KE [MeV], charge [fC] and
transmission (fraction of the cathode charge still in the beam).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AGENTIC_ROOT = Path(os.environ.get('AGENTIC_ROOT',
                                   '/sdf/group/mli/zhezhang/ued/agentic'))
DECK = HERE / 'ued_bringup.in'
FIELDMAP_DIR = AGENTIC_ROOT / 'UED_May2025'
FIELDMAPS = ('gun1Dmap.gdf', 'gunSolenoid_v0_bucking.gdf',
             'nano_ued_solenoid.gdf')
SCRATCH = Path(os.environ.get('GPTSIM_SCRATCH', AGENTIC_ROOT / 'runs' / 'sim'))

sys.path.insert(0, str(FIELDMAP_DIR))
from parse_gdf import gdftopandas  # noqa: E402  (colleague's GDF reader)

CORRECTORS = [f'{p}c{i:02d}' for i in range(6) for p in 'xy']

# The fixed screens in ued_bringup.in. A screen that no particle reaches is
# absent from the GPT output; run() adds it back with zero charge.
SCREENS = (0.50, 0.80, 1.499, 2.487, 3.988, 4.631)

# The May 2025 working point; kicks, offsets and quads off.
DEFAULTS = {
    'numParticle': 10000,    # 62500 for full fidelity (~3 min)
    'Qtot': -10e-15,
    'radius': 100e-6,
    'sc': 1,
    'gunAmp': -68e6,
    'gunPhaseDeg': 37,
    'sol1Fac': 0.25,
    'sol2Fac': 4.2,
    'x0': 0.0,
    'y0': 0.0,
    'coll': 1,
    'collR': 47e-6,
    'collx': 0.0,
    'gq1': 0.0,
    'gq2': 0.0,
    'dz': 0.0,
    'zstop': 4.7,
    **{c: 0.0 for c in CORRECTORS},
}

STATS = ('avgx', 'avgy', 'avgBx', 'avgBy', 'avgBz', 'stdx', 'stdy', 'stdt',
         'avgG', 'stdG', 'nemixrms', 'nemiyrms', 'Q')


def _fmt(v):
    return f'{v:.10g}' if isinstance(v, (int, float)) else str(v)


def run(params=None, run_dir=None, ncpu=1, keep=False):
    """Run one simulation. Unknown parameter names raise KeyError."""
    p = dict(DEFAULTS)
    for k, v in (params or {}).items():
        if k not in DEFAULTS:
            raise KeyError(f'unknown deck parameter {k!r}')
        p[k] = v

    SCRATCH.mkdir(parents=True, exist_ok=True)
    work = Path(run_dir) if run_dir else Path(tempfile.mkdtemp(dir=SCRATCH))
    work.mkdir(parents=True, exist_ok=True)
    for f in FIELDMAPS:
        link = work / f
        if not link.exists():
            link.symlink_to(FIELDMAP_DIR / f)

    cmd = ['gpt', '-j', str(ncpu), '-o', 'out.gdf', str(DECK)]
    cmd += [f'{k}={_fmt(v)}' for k, v in p.items()]
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if res.returncode != 0 or not (work / 'out.gdf').exists():
        raise RuntimeError(f'gpt failed in {work}:\n{res.stderr[-2000:]}')
    subprocess.run(['gdfa', '-o', 'stats.gdf', 'out.gdf', 'position',
                    *STATS], cwd=work, check=True, capture_output=True)

    _, _, s = gdftopandas(str(work / 'stats.gdf'))
    s = s.sort_values('position').reset_index(drop=True)
    df = pd.DataFrame({
        'z': s['position'],
        'x_um': s['avgx'] * 1e6,
        'y_um': s['avgy'] * 1e6,
        'xp_mrad': s['avgBx'] / s['avgBz'] * 1e3,
        'yp_mrad': s['avgBy'] / s['avgBz'] * 1e3,
        'sx_um': s['stdx'] * 1e6,
        'sy_um': s['stdy'] * 1e6,
        'st_fs': s['stdt'] * 1e15,
        'KE_MeV': (s['avgG'] - 1) * 0.51099895,
        'dE_rel': s['stdG'] / (s['avgG'] - 1),
        'enx_nm': s['nemixrms'] * 1e9,
        'eny_nm': s['nemiyrms'] * 1e9,
        'Q_fC': s['Q'] * 1e15,
        'transmission': s['Q'] / p['Qtot'],
    })
    missing = [z for z in SCREENS
               if not np.any(np.abs(df['z'].to_numpy() - z) < 1e-6)]
    if missing:  # beam lost before these screens
        lost = pd.DataFrame({'z': missing, 'Q_fC': 0.0, 'transmission': 0.0})
        df = pd.concat([df, lost], ignore_index=True)
        df = df.sort_values('z').reset_index(drop=True)
    df.attrs['params'] = p
    df.attrs['run_dir'] = str(work)
    if keep:
        df.to_csv(work / 'stats.csv', index=False)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return df


def scan(param_list, workers=None, ncpu=1):
    """Run many simulations in parallel (one GPT process each)."""
    workers = workers or min(len(param_list), 64)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda q: run(q, ncpu=ncpu), param_list))


def at(df, z, tol=5e-3):
    """Row of the screen at z (within tol metres); KeyError if none."""
    dist = np.abs(df['z'].to_numpy() - z)
    i = int(np.argmin(dist))
    if dist[i] > tol:
        raise KeyError(f'no screen within {tol} m of z={z}')
    return df.iloc[i]
