#!/usr/bin/env python
"""Camera frames for a snapshot: read-only (caget of the latest frames).

    python fj_snapshot_images.py OUT_PREFIX

Writes OUT_PREFIX.npz (the frames) and OUT_PREFIX.png (one panel per
camera, with the frame counter, the maximum and the total counts). A frame
is whatever the camera last acquired: nothing is triggered or changed. A
camera that doesn't answer gets an empty panel saying so.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numpy as np  # noqa: E402

CAMS = ('cam_vcc', 'cam_diag_yag', 'cam_sample_yag', 'cam_far_andor')


def grab(backend, cams=CAMS):
    frames, notes = {}, {}
    for cam in cams:
        try:
            counter, img, full, _ = backend._frame(cam)
            frames[cam] = np.asarray(img)
            notes[cam] = f'frame {int(counter)}, full scale {full}'
        except Exception as exc:
            notes[cam] = f'not read: {exc}'
    return frames, notes


def draw(frames, notes, png, title=''):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    cams = list(notes)
    fig, axes = plt.subplots(1, len(cams), figsize=(4.6 * len(cams), 4.8))
    for ax, cam in zip(np.atleast_1d(axes), cams):
        img = frames.get(cam)
        if img is None:
            ax.text(0.5, 0.5, notes[cam], ha='center', va='center',
                    wrap=True, fontsize=8, transform=ax.transAxes)
            ax.set_xticks([]), ax.set_yticks([])
        else:
            lo, hi = np.percentile(img, [1, 99.9])
            ax.imshow(img, cmap='gray', vmin=lo, vmax=hi if hi > lo else lo + 1)
            ax.set_xlabel(f'{notes[cam]}\nmax {img.max():.0f}, '
                          f'total {img.sum():.4g}, shown {lo:.0f}-{hi:.0f}',
                          fontsize=8)
        ax.set_title(cam, fontsize=10)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)
    return png


def main():
    prefix = Path(sys.argv[1])
    from ued_tuning.epics_backend import EpicsBackend
    frames, notes = grab(EpicsBackend(2.0))
    if frames:
        np.savez_compressed(f'{prefix}.npz', **frames)
    for cam, note in notes.items():
        print(f'  {cam:<16}{note}')
    print(f'images  {draw(frames, notes, f"{prefix}.png", prefix.name)}')


if __name__ == '__main__':
    main()
