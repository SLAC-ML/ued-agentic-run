"""Two-bunch double-exponential simulator for the Schottky (gun-phase) scan.

theta (1D):
    T0 — the time-zero offset (scalar to be inferred).

nuisance (10D): [A, f1, tau1, tau2, tau_kick, sigma, y_shift, irf_sigma, alpha_kick, delta_T]
    A          : total step amplitude.
    f1         : fraction of amplitude in the fast component ∈ (0, 1).
    tau1       : fast exponential decay time constant.
    tau2       : slow exponential decay time constant.
    tau_kick   : decay time constant of the second-bunch kick.
    sigma      : noise scale.
    y_shift    : constant vertical offset added to the signal.
    irf_sigma  : width (std) of the Gaussian instrument-response function.
    alpha_kick : amplitude ratio of the second-bunch kick ∈ (0, 1).
    delta_T    : time separation between the two laser bunches (same units as T0).

Signal model (before IRF convolution):
    Main bunch (double exponential):
        f1*A*(exp(-(t-T0)/tau1) - 1)           for t >= T0
        (1-f1)*A*(exp(-(t-T0)/tau2) - 1)       for t >= T0
    Second bunch kick (single exponential):
        alpha_kick*A*(exp(-(t-T0-dT)/tau_kick) - 1)  for t >= T0+dT

The analytical Gaussian-IRF convolution uses erfcx for numerical stability.
Rising-step sign convention: signal increases at T0.

Ported from policy-boed (amortex.simulators.two_bunch). All training here uses
noise_type="gaussian".
"""

import math

import torch


class TwoBunchDoubleExp:
    """Double-exponential two-bunch simulator with Gaussian IRF convolution.

    Noise is controlled by ``noise_type``:
        - ``"uniform"``:  Uniform noise in [-sigma, sigma]  (default)
        - ``"gaussian"``: Gaussian noise with std = sigma
    """

    def __init__(
        self,
        tau_min: float = 1e-3,
        amp_min: float = 1e-6,
        irf_min: float = 1e-3,
        noise_type: str = "uniform",
        device: torch.device = None,
    ):
        if noise_type not in ("uniform", "gaussian"):
            raise ValueError(
                f"noise_type must be 'uniform' or 'gaussian', got '{noise_type}'"
            )
        self.device = device or torch.device("cpu")
        self.tau_min = tau_min
        self.amp_min = amp_min
        self.irf_min = irf_min
        self.noise_type = noise_type

    def __call__(
        self,
        xi: torch.Tensor,
        thetas: torch.Tensor,
        nuisance: torch.Tensor,
        noiseless: bool = False,
    ) -> torch.Tensor:
        """Simulate two-bunch observations.

        Args:
            xi: Measurement times, shape (N, 1)
            thetas: Time zero T0, shape (B, 1)
            nuisance: shape (B, 10), see module docstring
            noiseless: If True, return mean without noise

        Returns:
            Observations, shape (N, 1)
        """
        xi = xi.to(self.device)
        thetas = thetas.to(self.device)
        nuisance = nuisance.to(self.device)

        if nuisance.dim() == 1:
            nuisance = nuisance.unsqueeze(0)
        if thetas.dim() == 1:
            thetas = thetas.unsqueeze(0)
        if xi.dim() == 1:
            xi = xi.unsqueeze(1)

        A = nuisance[:, :1]
        f1 = nuisance[:, 1:2]
        tau1 = nuisance[:, 2:3]
        tau2 = nuisance[:, 3:4]
        tau_kick = nuisance[:, 4:5]
        sigma = nuisance[:, 5:6]
        y_shift = nuisance[:, 6:7]
        irf_sigma = nuisance[:, 7:8]
        alpha_kick = nuisance[:, 8:9]
        delta_T = nuisance[:, 9:10]

        A = torch.clip(A, min=self.amp_min)
        tau1 = torch.clip(tau1, min=self.tau_min)
        tau2 = torch.clip(tau2, min=self.tau_min)
        tau_kick = torch.clip(tau_kick, min=self.tau_min)
        irf_sigma = torch.clip(irf_sigma, min=self.irf_min)
        f1 = torch.clip(f1, min=0.0, max=1.0)

        n_xi = xi.shape[0]
        if A.shape[0] != n_xi:
            A = A.repeat(n_xi, 1)
            f1 = f1.repeat(n_xi, 1)
            tau1 = tau1.repeat(n_xi, 1)
            tau2 = tau2.repeat(n_xi, 1)
            tau_kick = tau_kick.repeat(n_xi, 1)
            sigma = sigma.repeat(n_xi, 1)
            y_shift = y_shift.repeat(n_xi, 1)
            irf_sigma = irf_sigma.repeat(n_xi, 1)
            alpha_kick = alpha_kick.repeat(n_xi, 1)
            delta_T = delta_T.repeat(n_xi, 1)
            thetas = thetas.repeat(n_xi, 1)

        xi = xi.view(-1, 1)
        s = irf_sigma
        sqrt2 = torch.tensor(2.0, dtype=xi.dtype, device=xi.device).sqrt()

        def exp_component(amp, tau_i, dt):
            """Analytically IRF-convolved single exponential component."""
            q = (s**2 / tau_i - dt) / (s * sqrt2)
            b1 = (
                (amp / 2)
                * torch.exp(-(dt**2) / (2 * s**2))
                * torch.special.erfcx(q.clamp(min=0))
            )
            b2 = (
                (amp / 2)
                * torch.exp((s**2 / (2 * tau_i**2) - dt / tau_i).clamp(max=0))
                * torch.special.erfc(q.clamp(max=0))
            )
            return torch.where(q >= 0, b1, b2)

        dt1 = xi - thetas  # main bunch
        dt2 = xi - (thetas + delta_T)  # second bunch kick

        # Step terms (rising-step convention: signal increases at T0)
        step_fast = -(f1 * A / 2) * (1 + torch.special.erf(dt1 / (s * sqrt2)))
        step_slow = -((1 - f1) * A / 2) * (1 + torch.special.erf(dt1 / (s * sqrt2)))
        step_kick = -(alpha_kick * A / 2) * (1 + torch.special.erf(dt2 / (s * sqrt2)))

        y_out = (
            -(exp_component(f1 * A, tau1, dt1) + step_fast)
            - (exp_component((1 - f1) * A, tau2, dt1) + step_slow)
            - (exp_component(alpha_kick * A, tau_kick, dt2) + step_kick)
            + y_shift
        )

        if not noiseless:
            if self.noise_type == "gaussian":
                y_out = y_out + sigma * torch.randn_like(y_out)
            else:
                y_out = y_out + (2 * sigma * torch.rand_like(y_out) - sigma)

        return y_out

    def log_prob(
        self,
        y: torch.Tensor,
        xi: torch.Tensor,
        thetas: torch.Tensor,
        nuisance: torch.Tensor,
    ) -> torch.Tensor:
        """Log-likelihood of observations, shape (B,)."""
        if nuisance.dim() == 1:
            nuisance = nuisance.unsqueeze(0)

        B_orig = thetas.shape[0]
        y_pred = self(xi, thetas, nuisance, noiseless=True)
        sigma = nuisance[:, 5:6]

        residuals = y - y_pred
        N = xi.shape[0]
        n_per = N // B_orig

        res_r = residuals.reshape(B_orig, n_per, -1)
        sigma_r = sigma.unsqueeze(1)

        if self.noise_type == "gaussian":
            log_prob = (
                -0.5 * ((res_r / sigma_r) ** 2)
                - torch.log(sigma_r)
                - 0.5 * math.log(2 * math.pi)
            ).sum(dim=(1, 2))
        else:
            log_2sigma = torch.log(2 * sigma + 1e-8)
            in_bounds = (res_r.abs() <= sigma_r).reshape(B_orig, -1).all(dim=-1)
            log_prob = -n_per * log_2sigma.squeeze(-1)
            log_prob = log_prob.clone()
            log_prob[~in_bounds] = float("-inf")

        return log_prob
