"""Non-amortized BOED for pump-probe time zero on the delay stage: an Xopt
generator that measures where the expected information gain is highest.

Ported from the 2026-04 beamtime (ued_tuning repo, BOED_t_zero/boed.py by
Ryan Roussel, and the double-exponential model of
boed_double_exp_2-stage.ipynb by Dylan Kennedy), with two changes:

  - every fit starts from the original priors and conditions on all the
    data. In April each fit used the previous posterior as its prior and
    conditioned on all the data again, counting the data once per step;
  - the next point is chosen among delays near t0 (candidate_range, a
    heuristic: margin_mm None restores April's whole window);
  - the measurement noise is learned (log-normal prior, eig_noise_prior),
    and the EIG's marginal guide uses the fitted noise. April pinned it
    near 0.135 (LogNormal(-2, 0.01)), and the guide used 0.05, well below
    the ~0.5-1 % scatter of the Bi Delta I/I.

In April the carried-forward posterior also served as the fit's starting
point; without it the fit sticks wherever it starts in t0. Here every fit
tries several starts (the last fit, the data's change point, points across
the window) briefly and finishes the best one (fit()).

The model: Delta I/I (%) is a double-exponential drop at t0, convolved
with a Gaussian instrument response, plus a baseline; the time is
dt = (t0 - delay) * ps/mm (drop toward lower delay) or (delay - t0) * ps/mm.
Its seven parameters (t0 in mm, a1, tau1_ps, a2, tau2_ps, baseline, irf_ps)
have Normal priors [loc, scale].

Used as a plain Xopt generator (X = Xopt(vocs, generator, evaluator);
X.step()), or one step at a time by ued_delay_eig.py for the ued_tuning
stage 8 (method='eig'). Needs torch, pyro-ppl and xopt.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
import pyro
import pyro.distributions as dist
import torch
from pyro.contrib.oed.eig import marginal_eig
from pyro.infer import SVI, Trace_ELBO
from xopt.generator import Generator

PS_PER_MM = 2e-3 / 299792458 * 1e12
PARAMS = ('t0_mm', 'a1', 'tau1_ps', 'a2', 'tau2_ps', 'baseline', 'irf_ps')
# April's priors (theta ~ N(-20, 10) about 210 mm), in this module's names.
APRIL_PRIORS = {'t0_mm': [190.0, 10.0], 'a1': [1.0, 0.5],
                'tau1_ps': [0.1, 0.1], 'a2': [4.0, 1.0],
                'tau2_ps': [1.0, 1.0], 'baseline': [-3.5, 0.5],
                'irf_ps': [0.1, 0.1]}


def signal(x_mm, t0_mm, a1, tau1_ps, a2, tau2_ps, baseline, irf_ps, sign=-1):
    """Delta I/I at delays x_mm: the IRF-convolved double-exponential drop
    (TimeZeroDoubleExp of the April notebook). sign = -1: the signal drops
    toward lower delay, +1: toward higher."""
    a1 = torch.clip(a1, min=1e-6)
    a2 = torch.clip(a2, min=1e-6)
    tau1 = torch.clip(tau1_ps, min=1e-3)
    tau2 = torch.clip(tau2_ps, min=1e-3)
    s = torch.clip(irf_ps, min=1e-3)
    dt = sign * (x_mm - t0_mm) * PS_PER_MM
    sqrt2 = math.sqrt(2.0)

    def component(a, tau):
        q = (s ** 2 / tau - dt) / (s * sqrt2)
        b1 = (a / 2) * torch.exp(-(dt ** 2) / (2 * s ** 2)) \
            * torch.special.erfcx(q.clamp(min=0))
        b2 = (a / 2) * torch.exp((s ** 2 / (2 * tau ** 2) - dt / tau)
                                 .clamp(max=0)) \
            * torch.special.erfc(q.clamp(max=0))
        return torch.where(q >= 0, b1, b2)

    step = -(a1 + a2) / 2 * (1 + torch.special.erf(dt / (s * sqrt2)))
    return component(a1, tau1) + component(a2, tau2) + step + baseline


def _model(dists, noise, sign):
    """A pyro model whose parameters follow `dists` (name -> (loc, scale)
    of a Normal) and whose noise follows LogNormal(*noise)."""
    def model(x):
        p = {k: pyro.sample(k, dist.Normal(torch.tensor(float(loc)),
                                           torch.tensor(float(sc))))
             .unsqueeze(-1) for k, (loc, sc) in dists.items()}
        out = signal(x, sign=sign, **p)
        sd = pyro.sample('noise', dist.LogNormal(
            torch.tensor(float(noise[0])), torch.tensor(float(noise[1])))
        ).unsqueeze(-1)
        with pyro.plate_stack('data', x.shape[:-1]):
            pyro.sample('y', dist.Normal(out, sd).to_event(1))
            return out
    return model


def _guide(init, noise_init):
    def guide(x):
        for k, (loc, sc) in init.items():
            pyro.sample(k, dist.Normal(
                pyro.param(f'{k}_loc', torch.tensor(float(loc))),
                pyro.param(f'{k}_scale', torch.tensor(float(sc)),
                           constraint=dist.constraints.positive)))
        pyro.sample('noise', dist.LogNormal(
            pyro.param('noise_loc', torch.tensor(float(noise_init[0]))),
            pyro.param('noise_scale', torch.tensor(float(noise_init[1])),
                       constraint=dist.constraints.positive)))
    return guide


class DelayEIGGenerator(Generator):
    """grid_steps grid points over the window (as X.grid_evaluate), then
    each point at the delay of highest expected information gain about the
    seven parameters, under the current posterior (mean-field Normal, fit
    by SVI), among n_candidates delays in candidate_range() (near t0 by
    default: a heuristic; margin_mm None for April's whole window)."""

    name = 'delay_eig'
    supports_no_objective: bool = True
    # Xopt 3.1 has no supports_no_objective and refuses a VOCS without an
    # objective: there the measurement rides as a (never optimized)
    # objective instead of an observable (ued_delay_eig.make_generator).
    supports_single_objective: bool = True
    priors: dict[str, list[float]] = dict(APRIL_PRIORS)
    noise_prior: list[float] = [-0.7, 0.75]      # LogNormal: median ~0.5 %
    signal_drops_toward: str = 'lower'
    grid_steps: int = 10
    n_candidates: int = 1000
    train_steps: int = 3000
    train_lr: float = 0.01
    n_starts: int = 5                            # t0 starts across the window
    margin_mm: Optional[float] = 0.5             # None: the whole window (April)
    eig_steps: int = 1000
    eig_samples: int = 100
    eig_final_samples: int = 10000
    init_params: Optional[dict[str, list[float]]] = None   # warm start
    posterior: Optional[dict[str, list[float]]] = None      # after fit()

    @property
    def sign(self):
        return -1 if self.signal_drops_toward == 'lower' else 1

    def _xy(self):
        x = torch.tensor(self.data[self.vocs.variable_names[0]].values).float()
        y_name = (self.vocs.observable_names or self.vocs.objective_names)[0]
        y = torch.tensor(self.data[y_name].values).float()
        return x, y

    def step_guess(self) -> float:
        """Change point of the data: the split that maximizes the mean
        before t0 minus the mean after it (a first guess for t0)."""
        x, y = (v.numpy() for v in self._xy())
        o = np.argsort(x)
        x, y = x[o], y[o]
        best, at = -np.inf, float(np.median(x))
        for i in range(2, len(x) - 1):
            lo, hi = y[:i].mean(), y[i:].mean()        # lower / higher delay
            gap = (hi - lo) if self.sign < 0 else (lo - hi)
            if gap > best:
                best, at = gap, 0.5 * (x[i - 1] + x[i])
        return float(at)

    def _svi(self, init, noise_init, steps, x, y):
        """SVI from `init`; returns (mean loss of the last 10 %, params)."""
        pyro.clear_param_store()
        prior = {k: self.priors[k] for k in PARAMS}
        model = pyro.condition(_model(prior, self.noise_prior, self.sign),
                               {'y': y})
        optim = pyro.optim.ExponentialLR({
            'optimizer': torch.optim.Adam,
            'optim_args': {'lr': self.train_lr, 'betas': (0.95, 0.999)},
            'gamma': 0.1 ** (1 / steps)})
        svi = SVI(model, _guide(init, noise_init), optim,
                  loss=Trace_ELBO(num_particles=10, vectorize_particles=True))
        losses = [svi.step(x) for _ in range(steps)]
        post = {k: [float(pyro.param(f'{k}_loc')),
                    float(pyro.param(f'{k}_scale'))] for k in PARAMS}
        post['noise'] = [float(pyro.param('noise_loc')),
                         float(pyro.param('noise_scale'))]
        return float(np.mean(losses[-max(steps // 10, 1):])), post

    def fit(self) -> dict:
        """Posterior of all parameters given all the data, from the
        original priors. The step in t0 makes the fit stick where it
        starts, so it starts from several t0: the previous fit, the data's
        change point, and n_starts points across the window; each runs
        train_steps / 6 steps, and the best (lowest loss) gets the full
        train_steps. Returns and keeps {name: [loc, scale]} (noise:
        log-normal)."""
        x, y = self._xy()
        base = {k: list(self.priors[k]) for k in PARAMS}
        noise_init = list(self.noise_prior)
        starts = []
        if self.init_params:
            prev = {k: v for k, v in self.init_params.items() if k in base}
            starts.append(dict(base, **prev))
            noise_init = self.init_params.get('noise', noise_init)
        lo, hi = self._window()
        width = (hi - lo) / max(self.n_starts, 1)
        for t in [self.step_guess(), *np.linspace(lo, hi, self.n_starts)]:
            starts.append(dict(base, t0_mm=[float(t), width / 4]))
        short = max(self.train_steps // 6, 50)
        runs = [self._svi(s0, noise_init, short, x, y) for s0 in starts]
        _, best = min(runs, key=lambda r: r[0])
        init = {k: best[k] for k in PARAMS}
        _, post = self._svi(init, best['noise'], self.train_steps, x, y)
        self.posterior = post
        return post

    def eig(self, designs: torch.Tensor) -> torch.Tensor:
        """log EIG at delays `designs` (C,), under the current posterior."""
        if self.posterior is None:
            self.fit()
        post = {k: self.posterior[k] for k in PARAMS}
        model = _model(post, self.posterior['noise'], self.sign)
        meas_sd = math.exp(self.posterior['noise'][0])     # fitted noise

        def marginal_guide(design, observation_labels, target_labels):
            q_y = pyro.param('q_y', torch.zeros(design.shape[-2:]))
            pyro.sample('y', dist.Normal(q_y, meas_sd).to_event(1))

        pyro.clear_param_store()
        optim = pyro.optim.ExponentialLR({
            'optimizer': torch.optim.Adam, 'optim_args': {'lr': 0.1},
            'gamma': 0.01 ** (1 / self.eig_steps)})
        e = marginal_eig(model, designs.view(-1, 1), 'y', list(PARAMS),
                         num_samples=self.eig_samples,
                         num_steps=self.eig_steps, guide=marginal_guide,
                         optim=optim,
                         final_num_samples=self.eig_final_samples)
        return torch.nan_to_num(e.log(), nan=float('-inf')).squeeze(-1)

    def _window(self):
        return (float(v) for v in self.vocs.bounds[0])   # [[lo, hi]]: 1 variable

    def grid(self):
        lo, hi = self._window()
        return np.linspace(lo, hi, self.grid_steps)

    def candidate_range(self):
        """Where the next point may go. A heuristic, not in April's code:
        the t0 posterior's 98 % interval widened by margin_mm, within the
        window. The EIG is about all seven parameters (marginal_eig has no
        nuisance parameters), so over the whole window it goes after the
        decay tail once t0 is known; this keeps the points where t0 is
        learned. Within the range the choice is a true EIG maximum, but
        this is not t0-targeted BOED. margin_mm None: the whole window, as
        in April."""
        lo, hi = self._window()
        if self.margin_mm is None:
            return lo, hi
        q = self.t0_summary()
        return (max(lo, q['q01'] - self.margin_mm),
                min(hi, q['q99'] + self.margin_mm))

    def generate(self, n_candidates: int = 1) -> list[dict]:
        n = 0 if self.data is None else len(self.data)
        name = self.vocs.variable_names[0]
        if n < self.grid_steps:
            return [{name: float(self.grid()[n])}] * n_candidates
        self.init_params = self.posterior or self.init_params
        self.fit()
        lo, hi = self.candidate_range()
        cands = torch.linspace(lo, hi, self.n_candidates)
        best = cands[int(torch.argmax(self.eig(cands)))]
        return [{name: float(best)}] * n_candidates

    def t0_summary(self) -> dict:
        """t0 (mm) from the fitted posterior: Normal(loc, scale)."""
        loc, sc = self.posterior['t0_mm']
        z = {1: -2.3263, 5: -1.6449, 95: 1.6449, 99: 2.3263}
        return {'median': loc, 'mean': loc, 'std': sc,
                **{f'q{p:02d}': loc + v * sc for p, v in z.items()}}


def frame(delay, y, observable='y'):
    return pd.DataFrame({'delay': np.asarray(delay, float),
                         observable: np.asarray(y, float)})
