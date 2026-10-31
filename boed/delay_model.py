"""The pump-probe time-zero signal model of the April 2026 beamtime.

Delta I/I (%) at a Bi ring vs the pump delay: a double-exponential drop
starting at t0, convolved with a Gaussian instrument response (IRF), plus
a baseline. Dylan Kennedy's TimeZeroDoubleExp (ued_tuning repo,
BOED_t_zero/boed_double_exp_2-stage.ipynb), written in delay-stage mm:

    dt = (t0 - delay) * ps/mm     the signal drops toward lower delay
    dt = (delay - t0) * ps/mm     ... toward higher delay

t0 is the onset of the drop, not its midpoint. Seven parameters: t0_mm,
a1 and tau1_ps (fast part), a2 and tau2_ps (slow part), baseline (%),
irf_ps. Needs torch only.
"""
from __future__ import annotations

import math

import torch

PS_PER_MM = 2e-3 / 299792458 * 1e12          # delay stage, double pass
PARAMS = ('t0_mm', 'a1', 'tau1_ps', 'a2', 'tau2_ps', 'baseline', 'irf_ps')
# April's Normal priors [loc, scale] (the notebook's theta ~ N(-20, 10)
# about 210 mm, so t0 ~ N(190, 10) mm).
APRIL_PRIORS = {'t0_mm': [190.0, 10.0], 'a1': [1.0, 0.5],
                'tau1_ps': [0.1, 0.1], 'a2': [4.0, 1.0],
                'tau2_ps': [1.0, 1.0], 'baseline': [-3.5, 0.5],
                'irf_ps': [0.1, 0.1]}


def signal(x_mm, t0_mm, a1, tau1_ps, a2, tau2_ps, baseline, irf_ps, sign=-1):
    """Delta I/I (%) at delays x_mm. sign -1: the signal drops toward lower
    delay (UED, April 2026), +1: toward higher."""
    a1 = torch.clip(a1, min=1e-6)
    a2 = torch.clip(a2, min=1e-6)
    tau1 = torch.clip(tau1_ps, min=1e-3)
    tau2 = torch.clip(tau2_ps, min=1e-3)
    s = torch.clip(irf_ps, min=1e-3)
    dt = sign * (x_mm - t0_mm) * PS_PER_MM
    sqrt2 = math.sqrt(2.0)

    def component(a, tau):
        # stable two-branch form of the IRF-convolved exponential
        q = (s ** 2 / tau - dt) / (s * sqrt2)
        b1 = (a / 2) * torch.exp(-(dt ** 2) / (2 * s ** 2)) \
            * torch.special.erfcx(q.clamp(min=0))
        b2 = (a / 2) * torch.exp((s ** 2 / (2 * tau ** 2) - dt / tau)
                                 .clamp(max=0)) \
            * torch.special.erfc(q.clamp(max=0))
        return torch.where(q >= 0, b1, b2)

    step = -(a1 + a2) / 2 * (1 + torch.special.erf(dt / (s * sqrt2)))
    return component(a1, tau1) + component(a2, tau2) + step + baseline
