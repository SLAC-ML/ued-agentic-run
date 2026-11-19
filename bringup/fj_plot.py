#!/usr/bin/env python
"""Plot one stage run saved by fj_run_stage.py (Fuhao Ji, 2026-11).

    python fj_plot.py RECORD_FOLDER        # writes RECORD_FOLDER/plot.png

RECORD_FOLDER holds result.json (the stage's result) and, when the cameras
could be read, images.npz (frames taken right after the stage). Needs only
numpy and matplotlib, so any Python will do if the runner's has none.
"""
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402


def _f(v, fmt='.3g'):
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return str(v)


def _pairs(seq):
    a = np.array([[np.nan if v is None else v for v in p] for p in seq or []],
                 dtype=float)
    return (a[:, 0], a[:, 1]) if a.size else (np.array([]), np.array([]))


def p_gun_ramp(ax, r):
    tr = r.get('ramp_trace') or []
    if not tr:
        return False
    t = np.array([p['t'] for p in tr], dtype=float)
    t = (t - t[0]) / 60.0
    ax.plot(t, [p['areq'] for p in tr], 'C0', label='AREQ')
    ax.set_xlabel('time [min]')
    ax.set_ylabel('AREQ', color='C0')
    a2 = ax.twinx()
    a2.plot(t, [p['temp'] for p in tr], 'C3', lw=1, label='gun temp')
    a2.set_ylabel('gun temp [C]', color='C3')
    a3 = ax.twinx()
    a3.plot(t, [p['aact'] for p in tr], 'C2', lw=1, ls='--')
    a3.set_yticks([])
    ax.set_title('gun ramp: AREQ (blue), AACT (green, scaled), temp (red)')
    return True


def p_schottky(ax, r):
    if not (r.get('coarse') or r.get('fine')):
        return False
    x, q = _pairs(r.get('coarse'))
    if x.size:
        ax.plot(x, q, 'o-', ms=3, label='coarse')
    x, q = _pairs(r.get('fine'))
    if x.size:
        ax.plot(x, q, 's', ms=3, color='C1', label='fine')
    if r.get('threshold_fC') is not None:
        ax.axhline(r['threshold_fC'], color='gray', ls='--',
                   label='threshold %s fC' % _f(r['threshold_fC']))
    if r.get('emission_phase_deg') is not None:
        ax.axvline(r['emission_phase_deg'], color='r',
                   label='emission %s deg' % _f(r['emission_phase_deg'], '.2f'))
    if r.get('operating_phase_deg') is not None:
        ax.axvline(r['operating_phase_deg'], color='g',
                   label='PREQ set %s deg' % _f(r['operating_phase_deg'], '.2f'))
    ax.set_xlabel('PREQ [deg]')
    ax.set_ylabel('scope charge [fC] (dark not subtracted)')
    ax.set_title('Schottky scan, throttle %s deg' % _f(r.get('throttle_deg')))
    ax.legend(fontsize=7)
    return True


def p_charge(ax, r):
    th, q = _pairs(r.get('iterations'))
    if not th.size:
        return False
    ax.plot(th, q, 'o-')
    for i, (a, b) in enumerate(zip(th, q), 1):
        ax.annotate(str(i), (a, b), textcoords='offset points', xytext=(4, 4))
    if r.get('target_fC') is not None:
        ax.axhline(r['target_fC'], color='g', ls=':',
                   label='target %s fC' % _f(r['target_fC']))
    ax.set_xlabel('UV throttle [deg]')
    ax.set_ylabel('scope charge [fC]')
    ax.set_title('bunch charge: final %s fC at %s deg' % (
        _f(r.get('charge_fC')), _f(r.get('throttle_deg'), '.2f')))
    ax.legend(fontsize=7)
    return True


def p_monitor(ax, r):
    s = r.get('samples') or []
    if not s:
        return False
    t = np.array([p['t_s'] for p in s], dtype=float)
    ax.plot(t - t[0], [p['charge_fC'] for p in s], 'o-')
    ax.set_xlabel('time [s]')
    ax.set_ylabel('scope charge [fC]')
    ax.set_title('charge: mean %s, std %s fC' % (_f(r.get('mean_fC')),
                                                 _f(r.get('std_fC'))))
    return True


def p_collimator(ax, r):
    if not r.get('scan_mm'):
        return False
    ax.plot(r['scan_mm'], r['scan_total'], 'o-', label='coarse')
    if r.get('fine_mm'):
        ax.plot(r['fine_mm'], r['fine_total'], 's-', ms=3, label='fine')
    if r.get('collimator_mm') is not None:
        ax.axvline(r['collimator_mm'], color='g',
                   label='set %s mm' % _f(r['collimator_mm'], '.3f'))
    ax.set_xlabel('collimator [mm]')
    ax.set_ylabel('Andor total counts')
    ax.set_title('collimator: transmission %s' % _f(r.get('transmission')))
    ax.legend(fontsize=7)
    return True


def p_overlap(ax, r):
    it = r.get('iterations') or []
    if not it:
        return False
    e = np.array([p['error_px'] for p in it], dtype=float)
    ax.plot(e[:, 0], e[:, 1], 'o-')
    for i, p in enumerate(e):
        ax.annotate(str(i), p, textcoords='offset points', xytext=(4, 4))
    ax.plot(0, 0, 'r+', ms=14, label='cross')
    ax.set_xlabel('laser - cross, x [px]')
    ax.set_ylabel('laser - cross, y [px]')
    ax.set_aspect('equal', 'datalim')
    ax.set_title('pump overlap: final error %s px' % _f(r.get('final_error_px')))
    ax.legend(fontsize=7)
    return True


def p_raster(ax, r):
    if not r.get('raster_intensity'):
        return False
    z = np.array([[np.nan if v is None else v for v in row]
                  for row in r['raster_intensity']], dtype=float)
    x, y = r['raster_x_mm'], r['raster_y_mm']
    im = ax.imshow(z, origin='lower', aspect='auto',
                   extent=[x[0], x[-1], y[0], y[-1]])
    plt.colorbar(im, ax=ax, label='Andor total')
    pos = r.get('position') or {}
    if 'x' in pos:
        ax.plot(pos['x'], pos['y'], 'r+', ms=14)
    ax.set_xlabel('sample x [mm]')
    ax.set_ylabel('sample y [mm]')
    ax.set_title('sample raster (+ = position set)')
    return True


PANELS = {'gun_ramp': p_gun_ramp, 'schottky_scan': p_schottky,
          'set_bunch_charge': p_charge, 'monitor_charge': p_monitor,
          'align_collimator': p_collimator, 'overlap_pump_laser': p_overlap,
          'tune_sample_position': p_raster}


def _image(ax, img, name, r):
    img = np.asarray(img, dtype=float)
    lo, hi = np.percentile(img, [1, 99.8])
    if name == 'cam_far_andor':
        img = np.log10(np.clip(img - lo, 1, None))
        lo, hi = 0, max(img.max(), 1e-9)
    ax.imshow(img, cmap='gray', vmin=lo, vmax=hi if hi > lo else lo + 1)
    yag = r.get('yag') or {}
    if name == 'cam_sample_yag':
        if yag.get('cross_px'):
            ax.plot(*yag['cross_px'], 'r+', ms=16, label='cross')
        if yag.get('ebeam_px'):
            ax.plot(*yag['ebeam_px'], 'cx', ms=8, label='e-beam')
        if yag.get('cross_px') or yag.get('ebeam_px'):
            ax.legend(fontsize=7)
    ax.set_title(name + (' (log)' if name == 'cam_far_andor' else ''))
    ax.set_xticks([])
    ax.set_yticks([])


def plot(folder):
    folder = Path(folder)
    r = json.loads((folder / 'result.json').read_text())
    images = {}
    if (folder / 'images.npz').exists():
        with np.load(folder / 'images.npz') as z:
            images = {k: z[k] for k in z.files}
    panel = PANELS.get(r.get('fj_stage'))
    n = (1 if panel else 0) + len(images)
    fig, axes = plt.subplots(1, max(n, 1), figsize=(5.5 * max(n, 1), 4.8),
                             squeeze=False)
    axes = list(axes[0])
    if panel:
        ax = axes.pop(0)
        try:
            if not panel(ax, r):
                ax.text(0.5, 0.5, 'no scan data in this result',
                        ha='center', transform=ax.transAxes)
        except Exception as exc:
            ax.text(0.5, 0.5, 'plot failed: %s' % exc, ha='center',
                    transform=ax.transAxes)
    for (name, img), ax in zip(sorted(images.items()), axes):
        try:
            _image(ax, img, name, r)
        except Exception as exc:
            ax.text(0.5, 0.5, 'image failed: %s' % exc, ha='center',
                    transform=ax.transAxes)
    if n == 0:
        axes[0].axis('off')
    verdict = 'ACCEPTED' if r.get('accepted') else (
        'needs operator' if r.get('needs_operator') else 'not accepted')
    fig.suptitle('%s | %s | %s | %s\n%s' % (
        r.get('fj_stage'), r.get('fj_time', ''), r.get('mode', ''), verdict,
        str(r.get('reason', ''))[:150]), fontsize=10,
        color='k' if r.get('accepted') else 'C3')
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    out = folder / 'plot.png'
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(plot(sys.argv[1]))
