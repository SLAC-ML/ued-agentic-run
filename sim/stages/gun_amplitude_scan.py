#!/usr/bin/env python
"""Beam vs gun amplitude setpoint, the beam side of the gun ramp-up.

ramp_rf.py steps the amplitude setpoint (SIOC:AS01:KY03:0:AREQ) from 0.05 to
the operating 0.53. This scan shows the beam the gun would produce along that
ramp, at the May 2025 phase and solenoid settings.

ASSUMPTION: field is linear in AREQ, with AREQ = 0.53 giving the deck's
68 MV/m. Replace GUN_MV_PER_AREQ once the AREQ -> MV/m calibration is known.

    python gun_amplitude_scan.py [--n 13] [--out DIR]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gptsim import SCRATCH, at, scan  # noqa: E402

AREQ_OPERATING = 0.53
GUN_MV_PER_AREQ = 68.0 / AREQ_OPERATING   # assumed linear calibration
RAMP_START = 0.05


def plot(out, df):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ink2, grid, surf, blue = '#52514e', '#e4e3df', '#fcfcfb', '#2a78d6'
    plt.rcParams.update({'axes.edgecolor': grid, 'axes.labelcolor': ink2,
                         'xtick.color': ink2, 'ytick.color': ink2,
                         'font.size': 10, 'figure.facecolor': surf,
                         'axes.facecolor': surf})
    fig, axes = plt.subplots(3, 1, figsize=(6.5, 7), sharex=True)
    rows = [('KE_MeV', 'kinetic energy (MeV)'),
            ('transmission_pct', 'collimator transmission (%)'),
            ('sx_sample_um', 'rms size at sample 1 (um)')]
    for ax, (col, label) in zip(axes, rows):
        ax.plot(df.areq, df[col], lw=2, color=blue, marker='o', ms=4)
        ax.set_ylabel(label)
        ax.grid(True, color=grid, lw=0.6)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
    axes[-1].set_xlabel('gun amplitude setpoint AREQ (assumed linear: '
                        f'{GUN_MV_PER_AREQ:.1f} MV/m per unit)')
    fig.tight_layout()
    fig.savefig(out / 'beam_vs_areq.png', dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--n', type=int, default=13)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    out = args.out or SCRATCH / time.strftime('gun_amp_%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)

    areq = np.linspace(RAMP_START, AREQ_OPERATING, args.n)
    t0 = time.time()
    dfs = scan([{'gunAmp': -GUN_MV_PER_AREQ * 1e6 * a} for a in areq])
    rows = []
    for a, d in zip(areq, dfs):
        coll, s1 = at(d, 0.80), at(d, 1.499)
        rows.append({'areq': a, 'gun_MV_per_m': GUN_MV_PER_AREQ * a,
                     'KE_MeV': coll.KE_MeV,
                     'transmission_pct': coll.transmission * 100,
                     'sx_sample_um': s1.sx_um, 'st_sample_fs': s1.st_fs,
                     'dE_rel_sample': s1.dE_rel})
    df = pd.DataFrame(rows)
    df.to_csv(out / 'beam_vs_areq.csv', index=False)
    plot(out, df)
    (out / 'summary.json').write_text(json.dumps({
        'assumed_MV_per_m_per_areq': GUN_MV_PER_AREQ,
        'wall_time_s': round(time.time() - t0, 1)}, indent=1))
    print(df.round(4).to_string(index=False))
    print(f'results in {out}')


if __name__ == '__main__':
    main()
