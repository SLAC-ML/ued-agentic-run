#!/usr/bin/env python
"""Run the gun ramp-up procedure against the virtual gun, three scenarios.

  nominal      ramp 0.05 -> 0.53 with no faults
  water_fault  the cooling water warms by 3 C at t = 300 s: the temperature
               gate holds the ramp, then aborts it
  afb_trip     the amplitude feedback trips at t = 400 s: the readback stops
               tracking the setpoint and the added check aborts

The gun model is a placeholder (sim/virtual_gun.py), so this exercises the
procedure's logic, not the machine's real timing.

    python gun_ramp_sim.py [--target 0.53] [--out DIR]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sim'))
sys.path.insert(0, str(ROOT / 'bringup'))
from gun_ramp import RampConfig, ramp  # noqa: E402
from virtual_gun import VirtualGun  # noqa: E402

SCENARIOS = {
    'nominal': (),
    'water_fault': ((300.0, 'water_step', 3.0),),
    'afb_trip': ((400.0, 'afb_trip', None),),
}


def plot(out, results, cfg):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ink2, grid, surf = '#52514e', '#e4e3df', '#fcfcfb'
    colors = ['#2a78d6', '#eb6834', '#1baf7a']
    plt.rcParams.update({'axes.edgecolor': grid, 'axes.labelcolor': ink2,
                         'xtick.color': ink2, 'ytick.color': ink2,
                         'font.size': 10, 'figure.facecolor': surf,
                         'axes.facecolor': surf})
    fig, axes = plt.subplots(2, 1, figsize=(7.5, 5.5), sharex=True)
    for (name, res), col in zip(results.items(), colors):
        t = [r['t'] / 60 for r in res.trace]
        axes[0].plot(t, [r['areq'] for r in res.trace], color=col, lw=2,
                     label=f'{name}: {res.reason}')
        axes[1].plot(t, [r['temp'] for r in res.trace], color=col, lw=2)
    for y in (cfg.temp_min, cfg.temp_max):
        axes[1].axhline(y, color=ink2, lw=1, ls=':')
    axes[0].set_ylabel('AREQ setpoint')
    axes[1].set_ylabel('gun body temperature (C)')
    axes[1].set_xlabel('time (min, simulated)')
    axes[0].legend(frameon=False, fontsize=9, loc='upper left')
    for ax in axes:
        ax.grid(True, color=grid, lw=0.6)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / 'ramp_scenarios.png', dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--target', type=float, default=0.53)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    out = args.out or Path('runs') / time.strftime('gun_ramp_%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)

    cfg = RampConfig(target=args.target)
    results = {name: ramp(VirtualGun(seed=1, faults=f), cfg)
               for name, f in SCENARIOS.items()}
    summary = {name: {'ok': r.ok, 'reason': r.reason,
                      'final_areq': r.final_areq,
                      'sim_time_min': round(r.trace[-1]['t'] / 60, 2),
                      'max_temp_C': round(max(x['temp'] for x in r.trace), 2)}
               for name, r in results.items()}
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    (out / 'traces.json').write_text(json.dumps(
        {name: r.trace for name, r in results.items()}))
    plot(out, results, cfg)
    print(json.dumps(summary, indent=1))
    print(f'results in {out}')


if __name__ == '__main__':
    main()
