"""Read-only EPICS backend for the UED tuning tools.

Reads a logical channel (channels.py) through its PV with caget. Every put
is refused: the UED agent never writes PVs (see agent/deploy/ued/README.md).
A stage run against this backend therefore stops at its first write, which
is the point — writes need a reviewed, human-approved path that does not
exist yet. Pre-checks and reads work wherever the PV is mapped and reachable.

Camera stats (centroid, sigma, total, ...) are computed here from the image
PV, not read from areaDetector Stats plugins: on 2026-10-16 the GigE cameras'
Stats plugins were disabled (reading 0.0, which looks like a real centroid)
and the Andor's ran on a 163x163 ROI.

Accelerator PVs (gun RF, magnets, correctors) need the CA address list that
ued_setup.sh sets on ued-daq: 172.21.36.255:5064 172.27.99.255:5058.
"""
from __future__ import annotations

import math
import time

import numpy as np

from .channels import CAMERAS, CHANNELS, STAT_NAMES, from_pv, to_pv


class WritesDisabled(RuntimeError):
    pass


class ChannelUnavailable(RuntimeError):
    pass


def image_stats(img, full_scale, max_bins=512, nsigma=8.0, level=0.25,
                max_area=0.25):
    """Beam stats of a 2D image: background-subtracted total, centroid and
    rms size (px, full-frame coordinates), raw max and saturation.

    The image is binned to at most `max_bins` per side and median-filtered,
    so hot pixels and cosmics don't count as a beam. The beam is the blob
    around the brightest point, down to `level` of its height, if that
    point stands `nsigma` robust sigmas above the background. A blob
    covering more than `max_area` of the frame is a glow, not a beam. With
    no beam the centroid and size are NaN.
    """
    from scipy import ndimage
    img = np.asarray(img, dtype=np.float64)
    ny, nx = img.shape
    b = max(1, math.ceil(max(nx, ny) / max_bins))
    by, bx = ny // b, nx // b
    binned = img[:by * b, :bx * b].reshape(by, b, bx, b).mean(axis=(1, 3))
    clean = ndimage.median_filter(binned, size=3)
    bkg = float(np.median(clean))
    noise = 1.4826 * float(np.median(np.abs(clean - bkg))) or \
        float(clean.std()) or 1.0
    raw_max = float(img.max())
    out = {'size_x': nx, 'size_y': ny, 'max_value': raw_max,
           'saturated': float(raw_max >= full_scale), 'total': 0.0,
           'centroid_x': math.nan, 'centroid_y': math.nan,
           'sigma_x': math.nan, 'sigma_y': math.nan}
    peak_at = np.unravel_index(int(np.argmax(clean)), clean.shape)
    height = float(clean[peak_at]) - bkg
    if height < nsigma * noise:
        return out
    labels, _ = ndimage.label(clean > bkg + level * height)
    blob = ndimage.binary_dilation(labels == labels[peak_at], iterations=2)
    sig = np.where(blob, np.clip(binned - bkg, 0.0, None), 0.0)
    out['total'] = float(sig.sum()) * b * b
    if blob.mean() > max_area or sig.sum() <= 0:
        return out
    w = sig / sig.sum()
    xs = (np.arange(bx) + 0.5) * b - 0.5
    ys = (np.arange(by) + 0.5) * b - 0.5
    px, py = w.sum(axis=0), w.sum(axis=1)
    cx, cy = float(px @ xs), float(py @ ys)
    out.update(centroid_x=cx, centroid_y=cy,
               sigma_x=math.sqrt(float(px @ (xs - cx) ** 2)),
               sigma_y=math.sqrt(float(py @ (ys - cy) ** 2)))
    return out


class EpicsBackend:
    kind = 'epics'

    def __init__(self, timeout=2.0):
        from epics import caget  # imported here: the sim never needs pyepics
        self._caget = caget
        self.timeout = timeout
        self._frames = {}     # camera -> (array counter, stats)

    def _read(self, pv, as_string=False, timeout=None):
        value = self._caget(pv, timeout=timeout or self.timeout,
                            as_string=as_string)
        if value is None:
            raise ChannelUnavailable(f'{pv} did not answer')
        return value

    def _frame(self, cam):
        """(counter, image, full scale) of the camera's latest frame, read
        once per frame."""
        prefix, plugin, _, _ = CAMERAS[cam]
        p = f'{prefix}:{plugin}'
        counter = self._read(f'{p}:ArrayCounter_RBV')
        cached = self._frames.get(cam)
        if cached and cached[0] == counter:
            return cached
        dims = [int(self._read(f'{p}:ArraySize{i}_RBV')) for i in range(3)]
        ndim = int(self._read(f'{p}:NDimensions_RBV'))
        dtype = str(self._read(f'{p}:DataType_RBV', as_string=True))
        bits = 16 if '16' in dtype else 32 if '32' in dtype else 8
        data = np.asarray(self._read(f'{p}:ArrayData', timeout=10.0))
        # CA delivers unsigned pixels as signed integers: undo the wrap
        data = data.astype(np.int64) & ((1 << bits) - 1)
        if ndim == 3 and dims[0] == 3:            # RGB1: colour, x, y
            n = dims[0] * dims[1] * dims[2]
            img = data[:n].reshape(dims[2], dims[1], 3).mean(axis=2)
        else:                                     # mono: x, y
            img = data[:dims[0] * dims[1]].reshape(dims[1], dims[0])
        frame = (counter, img, (1 << bits) - 1, None)
        self._frames[cam] = frame
        return frame

    def _camera_stats(self, cam):
        counter, img, full, stats = self._frame(cam)
        if stats is None:
            stats = image_stats(img, full_scale=full)
            self._frames[cam] = (counter, img, full, stats)
        return stats

    def image(self, cam):
        """The camera's latest frame, as a 2D array (RGB averaged)."""
        return self._frame(cam)[1]

    def get(self, name):
        ch = CHANNELS.get(name)
        if ch is None:
            raise KeyError(f'unknown channel {name!r}')
        if ch.pv is None:
            raise ChannelUnavailable(f'{name}: no PV known yet ({ch.status})')
        cam, _, stat = name.partition('.')
        try:
            if cam in CAMERAS and stat in STAT_NAMES:
                return self._camera_stats(cam)[stat]
            return from_pv(name, self._read(ch.pv,
                                            as_string=ch.as_string))
        except ChannelUnavailable as exc:
            raise ChannelUnavailable(f'{name}: {exc}') from None

    def put(self, name, value):
        raw = to_pv(name, value)
        shown = f'{value!r}' if raw == value else f'{value!r} ({raw!r} on the PV)'
        raise WritesDisabled(f'refused put {name}={shown}: this deployment '
                             'is read-only on the real machine')

    def sleep(self, seconds):
        time.sleep(seconds)

    def time(self):
        return time.time()
