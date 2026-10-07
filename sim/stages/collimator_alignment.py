#!/usr/bin/env python
"""Simulated collimator alignment, a beam-steering stage of UED bring-up.

Procedure (from Fuhao): XC/YC00, just before the collimator, steer the beam
through the 100 um hole; XC/YC01, just after it, bring the transmitted beam
back onto the target. Here the beam is misaligned by an offset of the laser
spot on the cathode, and the tuner only uses what the machine would show:
the transmitted charge and the beam centroid on the target screen (ANDOR1).

    python collimator_alignment.py [--x0 150e-6] [--y0 -100e-6] [--out DIR]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gptsim import SCRATCH, at, run, scan  # noqa: E402

Z_COLL = 0.80      # screen past the collimator: transmitted charge
Z_TARGET = 4.631   # ANDOR1 diffraction detector: steering target


def gauss2d(k, a, kx0, ky0, sx, sy, rho, c):
    u, v = (k[0] - kx0) / sx, (k[1] - ky0) / sy
    return a * np.exp(-(u * u - 2 * rho * u * v + v * v)
                      / (2 * (1 - rho * rho))) + c


def map_transmission(base, span, n):
    """Transmission through the collimator over an XC00 x YC00 grid."""
    k = np.linspace(-span, span, n)
    kx, ky = np.meshgrid(k, k)
    pts = list(zip(kx.ravel(), ky.ravel()))
    dfs = scan([{**base, 'xc00': a, 'yc00': b} for a, b in pts])
    t = np.array([at(d, Z_COLL).transmission for d in dfs]).reshape(kx.shape)
    return kx, ky, t


def fit_peak(kx, ky, t):
    i = np.unravel_index(np.argmax(t), t.shape)
    p0 = [t.max(), kx[i], ky[i], 0.3, 0.3, 0.0, 0.0]
    popt, _ = curve_fit(gauss2d, (kx.ravel(), ky.ravel()), t.ravel(), p0=p0,
                        maxfev=20000)
    return popt


def centroid(df, z=Z_TARGET):
    r = at(df, z)
    return np.array([r.x_um, r.y_um])


K01_LIMIT = 3.0    # mrad; no corrector setting outside this is trusted


def steer_to_target(base, d=0.2, iters=2):
    """Zero the ANDOR1 centroid with XC01/YC01 from a measured response."""
    k01 = np.zeros(2)
    hist = []
    for _ in range(iters):
        p = {**base, 'xc01': k01[0], 'yc01': k01[1]}
        r0, rx, ry = scan([p, {**p, 'xc01': k01[0] + d},
                           {**p, 'yc01': k01[1] + d}])
        c0 = centroid(r0)
        resp = np.column_stack([(centroid(rx) - c0) / d,
                                (centroid(ry) - c0) / d])  # um per mrad
        if not np.all(np.isfinite(resp)) or np.linalg.cond(resp) > 1e3:
            raise RuntimeError(f'XC01/YC01 response is unusable: {resp}')
        k01 = np.clip(k01 - np.linalg.solve(resp, c0), -K01_LIMIT, K01_LIMIT)
        hist.append({'centroid_um': c0.tolist(),
                     'response_um_per_mrad': resp.tolist(),
                     'next_k01_mrad': k01.tolist()})
    return k01, hist


def plot(out, kx, ky, t, peak, profiles):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    ink, ink2, grid, surf = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
    seq = LinearSegmentedColormap.from_list('blue', [
        '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95',
        '#0d366b'])
    series = ['#2a78d6', '#eb6834', '#1baf7a']
    plt.rcParams.update({'axes.edgecolor': grid, 'axes.labelcolor': ink2,
                         'xtick.color': ink2, 'ytick.color': ink2,
                         'text.color': ink, 'font.size': 10,
                         'figure.facecolor': surf, 'axes.facecolor': surf})

    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    m = ax.pcolormesh(kx, ky, t * 100, cmap=seq, shading='nearest')
    cb = fig.colorbar(m, ax=ax)
    cb.set_label('transmission through collimator (%)', color=ink2)
    cb.outline.set_visible(False)
    ax.plot(0, 0, 'o', ms=8, mfc='none', mec=ink, mew=2)
    ax.annotate('start', (0, 0), xytext=(6, 6), textcoords='offset points')
    ax.plot(peak[1], peak[2], 'P', ms=10, color=surf, mec=ink, mew=1.5)
    ax.annotate('found', (peak[1], peak[2]), xytext=(6, -12),
                textcoords='offset points')
    ax.set_xlabel('XC00 kick (mrad)')
    ax.set_ylabel('YC00 kick (mrad)')
    ax.set_aspect('equal')
    fig.tight_layout()
    fig.savefig(out / 'transmission_map.png', dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(7.5, 5), sharex=True,
                             sharey=True)
    for (label, df), col in zip(profiles.items(), series):
        for axis, q in zip(axes, ('x_um', 'y_um')):
            axis.plot(df.z, df[q], lw=2, color=col, label=label)
    for axis, name in zip(axes, ('x', 'y')):
        axis.axhline(0, color=grid, lw=1, zorder=0)
        axis.axvline(Z_TARGET, color=ink2, lw=1, ls=':')
        axis.set_ylabel(f'centroid {name} (um)')
        axis.grid(True, color=grid, lw=0.6)
        for s in ('top', 'right'):
            axis.spines[s].set_visible(False)
    axes[0].text(Z_TARGET, axes[0].get_ylim()[1], ' ANDOR1', va='top',
                 color=ink2, fontsize=9)
    axes[0].legend(frameon=False, loc='lower left')
    axes[1].set_xlabel('z (m)')
    fig.tight_layout()
    fig.savefig(out / 'centroid_vs_z.png', dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--x0', type=float, default=150e-6,
                    help='cathode spot offset x [m] (the hidden error)')
    ap.add_argument('--y0', type=float, default=-100e-6)
    ap.add_argument('--span', type=float, default=1.5,
                    help='XC00/YC00 scan half-range [mrad]')
    ap.add_argument('--n', type=int, default=11,
                    help='grid points per axis')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()

    out = args.out or SCRATCH / time.strftime('collimator_%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    err = {'x0': args.x0, 'y0': args.y0}
    t0 = time.time()

    start = run({**err, 'dz': 0.05})
    kx, ky, t = map_transmission(err, args.span, args.n)
    peak = fit_peak(kx, ky, t)
    k00 = {'xc00': peak[1], 'yc00': peak[2]}
    through = run({**err, **k00, 'dz': 0.05})
    k01, hist = steer_to_target({**err, **k00})
    final = run({**err, **k00, 'xc01': k01[0], 'yc01': k01[1], 'dz': 0.05})

    def state(df):
        return {'transmission': float(at(df, Z_COLL).transmission),
                'andor1_centroid_um': centroid(df).round(2).tolist(),
                'sample1_centroid_um': centroid(df, 1.499).round(2).tolist()}

    summary = {
        'misalignment': {'cathode_offset_um': [args.x0 * 1e6, args.y0 * 1e6]},
        'scan': {'span_mrad': args.span, 'n': args.n, 'runs': args.n ** 2},
        'xc00_yc00_mrad': [float(peak[1]), float(peak[2])],
        'transmission_peak_fit': float(peak[0] + peak[6]),
        'xc01_yc01_mrad': k01.round(4).tolist(),
        'steering_iterations': hist,
        'start': state(start),
        'after_xc00': state(through),
        'final': state(final),
        'wall_time_s': round(time.time() - t0, 1),
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    np.savez(out / 'transmission_map.npz', kx=kx, ky=ky, t=t)
    profiles = {'start': start, 'after XC/YC00': through,
                'after XC/YC01': final}
    for name, df in zip(('start', 'after_xc00', 'final'), profiles.values()):
        df.to_csv(out / f'profile_{name}.csv', index=False)
    plot(out, kx, ky, t, peak, profiles)
    print(json.dumps({k: summary[k] for k in (
        'misalignment', 'xc00_yc00_mrad', 'xc01_yc01_mrad', 'start',
        'after_xc00', 'final', 'wall_time_s')}, indent=1))
    print(f'results in {out}')


if __name__ == '__main__':
    main()
