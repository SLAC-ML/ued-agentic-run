#!/usr/bin/env python
"""Camera frames for a snapshot: read-only (caget of the latest frames).

    python fj_snapshot_images.py OUT_PREFIX

Writes OUT_PREFIX.npz (the frames) and OUT_PREFIX.png, one panel per camera:

    cam_vcc         false colour, zoomed to twice its ROI1 (ROI1 outlined)
    cam_diag_yag    false colour
    cam_sample_yag  the colour image as the camera gives it
    cam_far_andor   jet

A frame is whatever the camera last acquired: nothing is triggered or
changed. A camera that doesn't answer gets an empty panel saying so.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numpy as np  # noqa: E402

CAMS = ('cam_vcc', 'cam_diag_yag', 'cam_sample_yag', 'cam_far_andor')
CMAP = {'cam_vcc': 'inferno', 'cam_diag_yag': 'inferno',
        'cam_far_andor': 'jet'}
ZOOM_ROI = {'cam_vcc': 2.0}          # window = this many times ROI1


def read_frame(backend, cam):
    """(counter, image, full scale); a colour camera keeps its 3 planes."""
    from ued_tuning.channels import CAMERAS
    prefix, plugin = CAMERAS[cam][:2]
    p = f'{prefix}:{plugin}'
    counter = backend._read(f'{p}:ArrayCounter_RBV')
    dims = [int(backend._read(f'{p}:ArraySize{i}_RBV')) for i in range(3)]
    ndim = int(backend._read(f'{p}:NDimensions_RBV'))
    dtype = str(backend._read(f'{p}:DataType_RBV', as_string=True))
    bits = 16 if '16' in dtype else 32 if '32' in dtype else 8
    data = np.asarray(backend._read(f'{p}:ArrayData', timeout=10.0))
    data = data.astype(np.int64) & ((1 << bits) - 1)   # CA sends them signed
    if ndim == 3 and dims[0] == 3:                     # RGB1: colour, x, y
        img = data[:3 * dims[1] * dims[2]].reshape(dims[2], dims[1], 3)
    else:
        img = data[:dims[0] * dims[1]].reshape(dims[1], dims[0])
    return counter, img, (1 << bits) - 1


def read_roi(backend, cam):
    """ROI1 as (x0, y0, width, height) in pixels, or None."""
    from ued_tuning.channels import CAMERAS
    prefix = CAMERAS[cam][0]
    try:
        roi = [float(backend._read(f'{prefix}:ROI1:{s}'))
               for s in ('MinX', 'MinY', 'SizeX', 'SizeY')]
    except Exception:
        return None
    return roi if roi[2] > 0 and roi[3] > 0 else None


def grab(backend, cams=CAMS):
    frames, notes, rois = {}, {}, {}
    for cam in cams:
        try:
            counter, img, full = read_frame(backend, cam)
            frames[cam] = img
            notes[cam] = f'frame {int(counter)}, full scale {full}'
            if cam in ZOOM_ROI:
                rois[cam] = read_roi(backend, cam)
        except Exception as exc:
            notes[cam] = f'not read: {exc}'
    return frames, notes, rois


def draw(frames, notes, png, title='', rois=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    rois = rois or {}
    cams = list(notes)
    fig, axes = plt.subplots(1, len(cams), figsize=(4.8 * len(cams), 5.0))
    for ax, cam in zip(np.atleast_1d(axes), cams):
        img = frames.get(cam)
        ax.set_title(cam, fontsize=10)
        if img is None:
            ax.text(0.5, 0.5, notes[cam], ha='center', va='center',
                    wrap=True, fontsize=8, transform=ax.transAxes)
            ax.set_xticks([]), ax.set_yticks([])
            continue
        label = f'{notes[cam]}\nmax {img.max():.0f}, total {img.sum():.4g}'
        if img.ndim == 3:                       # colour: as the camera gives it
            full = float(notes[cam].rsplit(' ', 1)[-1])
            ax.imshow(np.clip(img / full, 0, 1))
            label += ', colour'
        else:
            lo, hi = np.percentile(img, [1, 99.9])
            im = ax.imshow(img, cmap=CMAP.get(cam, 'gray'), vmin=lo,
                           vmax=hi if hi > lo else lo + 1)
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        roi = rois.get(cam)
        if cam in ZOOM_ROI:
            if roi:
                x0, y0, w, h = roi
                k = ZOOM_ROI[cam]
                cx, cy = x0 + w / 2, y0 + h / 2
                ax.add_patch(Rectangle((x0, y0), w, h, fill=False,
                                       ec='white', lw=0.8, ls='--'))
                ax.set_xlim(cx - k * w / 2, cx + k * w / 2)
                ax.set_ylim(cy + k * h / 2, cy - k * h / 2)
                label += (f'\nROI1 ({x0:g}, {y0:g}) {w:g}x{h:g} px, '
                          f'window {k:g}x')
            else:
                label += '\nROI1 not read: full frame'
        ax.set_xlabel(label, fontsize=8)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)
    return png


def main():
    prefix = Path(sys.argv[1])
    from ued_tuning.epics_backend import EpicsBackend
    frames, notes, rois = grab(EpicsBackend(2.0))
    if frames:
        np.savez_compressed(f'{prefix}.npz', **frames)
    for cam, note in notes.items():
        print(f'  {cam:<16}{note}')
    print(f'images  {draw(frames, notes, f"{prefix}.png", prefix.name, rois)}')


if __name__ == '__main__':
    main()
