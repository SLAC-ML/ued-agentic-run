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

The rings are elliptical (b/a ~ 0.89 on 2026-10-30): with an ellipse
(fit_ring_ellipse, from Yusong Liu's ued1023440 analysis) the unwrapping
runs on the elliptical radius, so a ring stays in its few radial bins
instead of smearing over ~+-11 % of its radius.
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


def cartesian_to_polar(img, centre, n_r=500, n_theta=500, r_max=500.0,
                       ellipse=None):
    """(theta, r) resampling around centre, bilinear; outside the image
    reads 0, a NaN pixel spreads to its neighbours (as obj_pp). With
    ellipse = (b/a, theta of the major axis), r is the elliptical radius
    r_e, so an elliptical ring falls in one r bin (ellipse_radius)."""
    from scipy.ndimage import map_coordinates
    cx, cy = centre
    r = np.linspace(0.0, r_max, n_r)
    theta = np.linspace(0.0, 2 * np.pi, n_theta)
    rg, tg = np.meshgrid(r, theta, indexing='xy')
    if ellipse is not None:
        rg = ellipse_radius(rg, tg, *ellipse)
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


def profiles(stack, centre, hole, s_cal, corner_size=30, ellipse=None):
    """Normalized radial profiles of an image stack. hole = (x, y, r);
    ellipse = (b/a, theta) for elliptical rings (then s_cal is per pixel
    of the elliptical radius r_e), None for round ones (April)."""
    import warnings
    clean, _ = subtract_corner_median_stack(stack, corner_size)
    masked = apply_circular_nan_mask(clean, *hole)
    with warnings.catch_warnings():       # all-NaN columns inside the hole
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.array([radial_profile(
            cartesian_to_polar(im, centre, ellipse=ellipse)[0], s_cal)
            for im in masked])


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


# ------------------------------------------- elliptical rings (Yusong Liu)
# The Andor rings are not round: on 2026-10-30 (ued1023440, runs 2-10) the
# Bi 110 ring fitted b/a = 0.889 with the major axis 88 deg from +x, the
# same as in ued1023450. Ported from Yusong Liu's make_notebook.py
# (results/yusongl/Bi_T0_r2-10): the ring is fitted with an ellipse
# (centre, a, b, theta), and profiles use the area-preserving elliptical
# radius r_e = sqrt(u^2 b/a + v^2 a/b), (u, v) along the axes. Image frame:
# x = column, y = row, theta from +x toward +y.

def ellipse_radius(r_e, phi, b_over_a, theta):
    """Image radius, at azimuth phi (rad), of the point at elliptical
    radius r_e (ell_xy)."""
    return r_e / np.sqrt(np.cos(phi - theta) ** 2 * b_over_a
                         + np.sin(phi - theta) ** 2 / b_over_a)


def elliptical_radius(shape, geo):
    """r_e and azimuth (deg) of every pixel for geo = (cy, cx, a, b,
    theta) (ell_r)."""
    cy, cx, a, b, th = geo
    yy, xx = np.indices(shape)
    dy, dx = yy - cy, xx - cx
    u = dx * np.cos(th) + dy * np.sin(th)
    v = -dx * np.sin(th) + dy * np.cos(th)
    return (np.sqrt(u ** 2 * b / a + v ** 2 * a / b),
            np.rad2deg(np.arctan2(dy, dx)))


def _profile_bins(img, radius, mask, rmax):
    ri = radius.astype(int)
    ok = mask & (ri < rmax)
    n = np.bincount(ri[ok], minlength=rmax)
    s = np.bincount(ri[ok], img[ok], minlength=rmax)
    return np.where(n > 0, s / np.maximum(n, 1), np.nan)


def _subpix(p, i):
    if i <= 0 or i >= len(p) - 1 or not np.all(np.isfinite(p[i - 1:i + 2])):
        return float(i)
    den = p[i - 1] - 2 * p[i] + p[i + 1]
    return i + (0.5 * (p[i - 1] - p[i + 1]) / den if den != 0 else 0.0)


def _ring_points(img, mask, geo, r_lo, r_hi, nsec=72, min_px=40):
    """The ring's peak r_e in nsec azimuthal sectors, as image points
    (row, col) (ring_points)."""
    re, phi = elliptical_radius(img.shape, geo)
    edges = np.linspace(-180, 180, nsec + 1)
    sel = mask & (re >= r_lo) & (re < r_hi)
    cy, cx, a, b, th = geo
    pts = []
    for k in range(nsec):
        m = sel & (phi >= edges[k]) & (phi < edges[k + 1])
        if m.sum() < min_px:
            continue
        p = _profile_bins(img, re, m, int(r_hi) + 1)[int(r_lo):int(r_hi)]
        if np.isnan(p).sum() > 0.2 * len(p):
            continue
        i = int(np.nanargmax(p))
        if i in (0, len(p) - 1):
            continue
        az = np.deg2rad(0.5 * (edges[k] + edges[k + 1]))
        r = ellipse_radius(r_lo + _subpix(p, i), az, b / a, th)
        pts.append((cy + r * np.sin(az), cx + r * np.cos(az)))
    return np.array(pts)


def _fit_ellipse(y, x, p0):
    """Least-squares ellipse (cy, cx, a, b, theta), a >= b (fit_ellipse)."""
    from scipy.optimize import least_squares

    def res(q):
        cy, cx, a, b, th = q
        u = (x - cx) * np.cos(th) + (y - cy) * np.sin(th)
        v = -(x - cx) * np.sin(th) + (y - cy) * np.cos(th)
        return (np.sqrt((u / a) ** 2 + (v / b) ** 2) - 1) * np.sqrt(a * b)
    q = least_squares(res, p0, loss='soft_l1', f_scale=1.0).x
    cy, cx, a, b, th = q
    if a < b:
        a, b, th = b, a, th + np.pi / 2
    return ((cy, cx, abs(a), abs(b), (th + np.pi / 2) % np.pi - np.pi / 2),
            res(q))


def fit_ring_ellipse(img, centre, r_e, b_over_a, theta, border=6):
    """Fit an ellipse to one ring of a (background-subtracted, hole-masked)
    image, as Yusong Liu's notebook does for Bi 110: ring points in 72
    sectors within +-20 px, then +-10 px, of r_e around the current fit,
    each pass refitted. centre (x, y), r_e (px) and (b_over_a, theta) are
    the starting point. Returns centre, b/a, theta (rad), a, b and the rms
    residual (px)."""
    from scipy.ndimage import median_filter
    img = np.asarray(img, dtype=np.float64)
    mask = np.isfinite(img)
    mask[:border, :] = mask[-border:, :] = False
    mask[:, :border] = mask[:, -border:] = False
    work = median_filter(np.nan_to_num(img, nan=0.0), 3)
    a0 = r_e / np.sqrt(b_over_a)
    geo = (centre[1], centre[0], a0, a0 * b_over_a, theta)
    res, pts = np.array([np.nan]), np.empty((0, 2))
    for w in (20, 10):
        r1 = np.sqrt(geo[2] * geo[3])
        pts = _ring_points(work, mask, geo, r1 - w, r1 + w)
        if len(pts) < 12:
            raise ValueError(f'only {len(pts)} sectors show the ring near '
                             f'r_e = {r1:.0f} px')
        geo, res = _fit_ellipse(pts[:, 0], pts[:, 1], list(geo))
    cy, cx, a, b, th = geo
    return {'centre_px': [float(cx), float(cy)], 'b_over_a': float(b / a),
            'theta_rad': float(th), 'a_px': float(a), 'b_px': float(b),
            'rms_px': float(np.std(res)), 'n_sectors': int(len(pts))}
