"""Bi pump-probe signal from far-detector Andor images (stage 8).

Ported from the 2026-04 beamtime code in the ued_tuning repo, keeping its
arithmetic: Fuhao Ji's bi_pp_signal_2026.py (BiPPSignal.measure) and the
obj_pp.py helpers it uses, and Zhe Zhang's find_ring_center.py (grid search
plus Nelder-Mead on the azimuthal MAD). Plotting and file saving are left
out; the stage keeps the records.

The measurement at one delay is four frames, pump ON, OFF, OFF, ON. Each
frame: subtract the median of its four corner squares, NaN the Andor's
through hole, unwrap around the ring centre, and average over angle into a
radial profile normalized over s = 1.5..8 1/A. Delta I/I (%) per radius is
(mean ON - mean OFF) / mean OFF; the signal is its mean over +-8 radial
bins around the Bi ring (s = 7.30 1/A in April).
"""
from __future__ import annotations

import numpy as np


def subtract_corner_median_stack(stack, corner_size=30):
    """Each image minus the median of its four corner squares."""
    stack = np.asarray(stack, dtype=np.float64)
    n, h, w = stack.shape
    s = corner_size
    corners = np.stack([stack[:, :s, :s], stack[:, :s, w - s:],
                        stack[:, h - s:, :s], stack[:, h - s:, w - s:]],
                       axis=1).reshape(n, -1)
    med = np.median(corners, axis=1)
    return stack - med[:, None, None], med


def apply_circular_nan_mask(stack, cx, cy, radius):
    """NaN inside the circle (the through hole) of every image."""
    stack = np.array(stack, dtype=np.float64)
    _, h, w = stack.shape
    yy, xx = np.ogrid[:h, :w]
    stack[:, (xx - cx) ** 2 + (yy - cy) ** 2 <= radius ** 2] = np.nan
    return stack


def cartesian_to_polar(img, centre, n_r=500, n_theta=500, r_max=500.0):
    """(theta, r) resampling around centre, bilinear; outside the image
    reads 0, a NaN pixel spreads to its neighbours (as obj_pp)."""
    from scipy.ndimage import map_coordinates
    cx, cy = centre
    r = np.linspace(0.0, r_max, n_r)
    theta = np.linspace(0.0, 2 * np.pi, n_theta)
    rg, tg = np.meshgrid(r, theta, indexing='xy')
    x = cx + rg * np.cos(tg)
    y = cy + rg * np.sin(tg)
    polar = map_coordinates(img, [y.ravel(), x.ravel()], order=1).reshape(
        n_theta, n_r)
    return polar, r, theta


def radial_profile(polar, s_cal, s_low=1.5, s_high=8.0, norm=True):
    prof = np.nanmean(polar, axis=0)
    if norm:
        prof = prof / np.nanmean(prof[int(s_low / s_cal):int(s_high / s_cal)])
    return prof


def profiles(stack, centre, hole, s_cal, corner_size=30):
    """Normalized radial profiles of an image stack. hole = (x, y, r)."""
    import warnings
    clean, _ = subtract_corner_median_stack(stack, corner_size)
    masked = apply_circular_nan_mask(clean, *hole)
    with warnings.catch_warnings():       # all-NaN columns inside the hole
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.array([radial_profile(cartesian_to_polar(im, centre)[0],
                                        s_cal) for im in masked])


def delta_i_over_i(on, off, band=None):
    """Delta I/I (%) from ON and OFF profiles (arrays, one row per frame),
    averaged over the index band [lo, hi) (None: all of it). A scalar
    reading per frame (the simulator) is a profile of length 1."""
    on = np.atleast_2d(np.asarray(on, dtype=float))
    off = np.atleast_2d(np.asarray(off, dtype=float))
    ref = off.mean(axis=0)
    diff = (on.mean(axis=0) - ref) / (ref + 1e-5) * 100
    lo, hi = band if band is not None else (0, diff.shape[0])
    return float(np.nanmean(diff[lo:hi]))


def ring_band(ring_s, s_cal, half_width):
    """Profile indices +-half_width around the ring (as BiPPSignal)."""
    i = int(ring_s / s_cal)
    return i - half_width, i + half_width


# ------------------------------------------------- ring centre (Zhe Zhang)
def _azimuthal_mad(centre, data, r_min, r_max, n_radii=40, n_angles=360):
    from scipy.ndimage import map_coordinates
    cx, cy = centre
    ny, nx = data.shape
    ang = np.linspace(0, 2 * np.pi, n_angles, endpoint=False)
    total, rings = 0.0, 0
    for r in np.linspace(r_min, r_max, n_radii):
        x = cx + r * np.cos(ang)
        y = cy + r * np.sin(ang)
        inb = (x >= 0) & (x < nx - 1) & (y >= 0) & (y < ny - 1)
        if inb.sum() < n_angles * 0.5:
            continue
        v = map_coordinates(data, np.array([y, x]), order=1,
                            mode='constant', cval=np.nan)[inb]
        v = v[~np.isnan(v)]
        if len(v) < 10:
            continue
        total += np.median(np.abs(v - np.median(v)))
        rings += 1
    return total / rings if rings else np.inf


def find_ring_center(img, r_min=80.0, r_max=450.0, hole_radius=50.0,
                     search_px=30, step_px=5):
    """Ring centre (x, y): log image, light smoothing, intensity-weighted
    first guess, a grid search of +-search_px, then Nelder-Mead on the
    azimuthal MAD (find_ring_center(method='grid', use_mad=True)). One
    change: pixels below 0 (after the corner subtraction) are clipped to 0
    before the log, where the original made them NaN."""
    from scipy.ndimage import gaussian_filter
    from scipy.optimize import minimize
    ny, nx = img.shape
    work = gaussian_filter(np.log1p(np.nan_to_num(
        np.asarray(img, dtype=np.float64), nan=0.0).clip(min=0)), sigma=1)
    yy, xx = np.mgrid[0:ny, 0:nx]
    d = np.hypot(xx - nx / 2, yy - ny / 2)
    m = work * ((d > hole_radius) & (d < r_max))
    tot = m.sum()
    c0 = ((xx * m).sum() / tot, (yy * m).sum() / tot) if tot > 0 else (
        nx / 2, ny / 2)

    def f(c):
        return _azimuthal_mad(c, work, r_min, r_max)

    best, best_c = np.inf, c0
    for cx in np.arange(c0[0] - search_px, c0[0] + search_px + 1, step_px):
        for cy in np.arange(c0[1] - search_px, c0[1] + search_px + 1,
                            step_px):
            v = f((cx, cy))
            if v < best:
                best, best_c = v, (cx, cy)
    res = minimize(f, best_c, method='Nelder-Mead',
                   options={'xatol': 0.01, 'fatol': 1e-10, 'maxiter': 500})
    return float(res.x[0]), float(res.x[1])
