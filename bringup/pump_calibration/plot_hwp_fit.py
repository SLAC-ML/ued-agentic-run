"""Plot the 400 nm pump energy vs Harmonics HWP fit (data 2026-10-28)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

th = np.array([52, 50, 48, 46, 44, 42, 40, 38, 36, 34, 32, 30, 28, 26, 25, 24, 23.])
E = np.array([16.8, 17, 16.9, 16.5, 15.8, 14.7, 13.6, 12.2, 10.8, 9.3, 7.7, 6.4,
              5.1, 3.95, 3.4, 2.95, 2.5])
cos2 = lambda x, t0: np.cos(np.radians(2 * (x - t0))) ** 2
fit = lambda x: 0.413 + 16.600 * cos2(x, 49.65) ** 2            # rms 0.036 uJ
b = (cos2(th, 49.78) + 0.048) ** 2
leak = lambda x, A=(b @ E) / (b @ b): A * (cos2(x, 49.78) + 0.048) ** 2  # rms 0.038 uJ

ink, muted, blue, orange = '#1f1f1e', '#6b6a64', '#2a78d6', '#eb6834'
fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
x_in, x_out = np.linspace(23, 53, 300), np.linspace(3, 23, 200)
ax.plot(x_in, fit(x_in), color=blue, lw=2, label='Fit: 0.41 + 16.6 cos$^4$(2(HWP − 49.65°)) µJ')
ax.plot(x_out, fit(x_out), color=blue, lw=2, ls='--', label='Fit, extrapolated (no data below 23°)')
ax.plot(x_out, leak(x_out), color=muted, lw=1.5, ls=':',
        label='Alternative model, equally good fit: A (cos$^2$ + 0.048)$^2$')
ax.plot(th, E, 'o', ms=6, mfc='white', mec=ink, mew=1.5, label='Measured (PM1)')
for ang, txt, off, ha in ((8, 'YAG 8°\n0.06–0.42 µJ', (6, 22), 'left'),
                         (22, 'Bi t₀ 22°\n2.2 µJ, 2.3 mJ/cm²', (-10, 18), 'right'),
                         (25, 'Bi wide scan 25°\n3.4 µJ, 3.7 mJ/cm²', (12, -34), 'left')):
    y = float(fit(ang))
    ax.plot(ang, y, 'D', ms=8, color=orange, mec='white', mew=1.5, zorder=5)
    ax.annotate(txt, (ang, y), xytext=off, textcoords='offset points', ha=ha,
                fontsize=8.5, color=ink)
sec = ax.secondary_yaxis('right', functions=(lambda e: e * 0.636 * 1.7126,
                                             lambda f: f / (0.636 * 1.7126)))
sec.set_ylabel('Peak fluence at the sample (mJ/cm²)', color=muted)
ax.set_xlabel('Harmonics HWP (deg)'); ax.set_ylabel('400 nm energy at PM1 (µJ)')
ax.set_title('400 nm pump energy vs Harmonics HWP (2026-10-28, pump throttle 16°)',
             fontsize=10.5, loc='left', color=ink)
ax.set_xlim(2, 54); ax.set_ylim(0, 18.5)
ax.grid(color='#e6e5e0', lw=0.8); ax.set_axisbelow(True)
for s in ('top',): ax.spines[s].set_visible(False)
ax.legend(fontsize=8, frameon=False, loc='upper left')
fig.text(0.01, 0.01, 'Fluence: PM1 x 0.636 transmission to the sample, 227 µm FWHM spot, '
         'incident peak (4 ln2 / π / FWHM²).', fontsize=7.5, color=muted)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(__file__.replace('plot_hwp_fit.py', 'hwp_fit_400nm_20261028.png'))
