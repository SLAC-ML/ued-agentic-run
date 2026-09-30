#!/usr/bin/env python
"""Check a GPT run of the UED_May2025 deck.

Reports the same beam properties as check_single_run_1p6cell_10fC.ipynb at
the 1st-chamber sample plane and compares them with the numbers that notebook
printed for the colleague's reference run (GPT on Windows). Optionally diffs
the full z-evolution of the gdfa moments against another run.

    python check_run.py RUN_DIR [--compare OTHER_RUN_DIR]
"""
import argparse
import os
import sys

import numpy as np

# The colleague's GDF reader (parse_gdf.py) lives with the deck
DECK_DIR = os.environ.get('UED_DECK_DIR',
                          '/sdf/group/mli/zhezhang/ued/agentic/UED_May2025')
sys.path.insert(0, DECK_DIR)
from parse_gdf import gdftopandas  # noqa: E402

STAT_FILE = 'UED_stat_10fC_1p6cell_3p1MeV.gdf'
Z_CHECK = 1.557  # 1st-chamber sample plane, as in the notebook
Q_MACRO = -10e-15 / 6.25e4  # Qtot / numParticle in UED_beamline.in
Z_IRIS = 0.5575  # 100 um collimator
Z_DOWNSTREAM = 0.75  # past where the collimator cut shows up in the screens

# Printed by the notebook at z = 1.5600 m for the reference run
REFERENCE = {
    'N': 4006,
    'sigma_t_fs': 76.250,
    'eps_n_nm': 4.856,
    'sigma_x_um': 27.126,
    'sigma_y_um': 26.973,
    'KE_MeV': 3.098,
    'dE_pct': 0.0615,
    'Q_fC': -0.641,
}
# Relative tolerance vs the reference. The collimator passes only ~6% of the
# 62.5k macroparticles, so which ~4k survive shifts with thread count and
# platform; the looser bounds on sigma_t / dE reflect that.
TOLERANCE = {
    'N': 0.02,
    'sigma_t_fs': 0.05,
    'eps_n_nm': 0.03,
    'sigma_x_um': 0.03,
    'sigma_y_um': 0.03,
    'KE_MeV': 0.001,
    'dE_pct': 0.10,
    'Q_fC': 0.02,
}


def load_stats(run_dir):
    _, _, stat = gdftopandas(os.path.join(run_dir, STAT_FILE))
    stat = stat.drop(columns='paramid').sort_values('position')
    return stat.reset_index(drop=True)


def metrics_at(stat, z):
    row = stat.iloc[np.argmin(np.abs(stat['position'].to_numpy() - z))]
    return {
        'z': row['position'],
        'N': row['Q'] / Q_MACRO,
        'sigma_t_fs': row['stdt'] * 1e15,
        'eps_n_nm': row['nemirrms'] * 1e9,
        'sigma_x_um': row['stdx'] * 1e6,
        'sigma_y_um': row['stdy'] * 1e6,
        'KE_MeV': (row['avgG'] - 1) * 0.511,
        'dE_pct': row['stdG'] / (row['avgG'] - 1) * 1e2,
        'Q_fC': row['Q'] * 1e15,
    }


def check_reference(stat):
    m = metrics_at(stat, Z_CHECK)
    print(f"At z = {m['z']:.4f} m (reference: notebook, Windows GPT run)")
    print(f"  {'quantity':<12}{'this run':>12}{'reference':>12}"
          f"{'rel diff':>10}{'tol':>8}")
    ok = True
    for key, ref in REFERENCE.items():
        rel = (m[key] - ref) / abs(ref)
        passed = abs(rel) <= TOLERANCE[key]
        ok &= passed
        print(f"  {key:<12}{m[key]:>12.4f}{ref:>12.4f}{rel:>+10.2%}"
              f"{TOLERANCE[key]:>8.1%}  {'ok' if passed else 'FAIL'}")
    return ok


def compare_runs(stat, other):
    merged = stat.merge(other, on='position', suffixes=('', '_other'))
    z = merged['position'].to_numpy()
    # Screens just past the iris are skipped: GPT removes the clipped
    # particles only at the end of the time step, so where the drop shows up
    # (0.59..0.68 m seen so far) varies from run to run.
    sections = {f'z < {Z_IRIS}': z < Z_IRIS, f'z >= {Z_DOWNSTREAM}':
                z >= Z_DOWNSTREAM}
    print(f"Max relative difference over {len(merged)} common screens:")
    print(f"  {'':<10}" + ''.join(f'{s:>16}' for s in sections))
    identical = True
    # On a screen every particle sits at the screen's z: avgz/stdz are trivial
    for col in stat.columns.drop(['position', 'avgz', 'stdz']):
        a = merged[col].to_numpy()
        b = merged[col + '_other'].to_numpy()
        rel = np.abs(a - b) / np.maximum(np.abs(a), np.finfo(float).tiny)
        print(f"  {col:<10}" + ''.join(f'{np.nanmax(rel[m]):>16.3e}'
                                       for m in sections.values()))
        identical &= np.array_equal(a, b, equal_nan=True)
    print(f"  bit-identical: {identical}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_dir')
    parser.add_argument('--compare', metavar='OTHER_RUN_DIR')
    args = parser.parse_args()

    stat = load_stats(args.run_dir)
    ok = check_reference(stat)
    if args.compare:
        print()
        compare_runs(stat, load_stats(args.compare))
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
