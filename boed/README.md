# Amortized T0 inference for the Schottky scan

Amortized posteriors for time zero (T0) from the gun-phase Schottky scan, and two ways of choosing where to measure next with them. Neither optimizes expected information gain directly. Both are cheap stand-ins for amortized Bayesian experimental design: the next points are placed using the current T0 posterior, which is a single network forward pass.

## The model

`simulator.py` holds the signal model: a rising double exponential that starts at T0, plus a kick from a second bunch at T0 + delta_T, convolved with a Gaussian instrument response. It has 1 parameter of interest (T0) and 10 nuisance parameters (amplitude, fast fraction, three decay times, noise, offset, IRF width, kick ratio, bunch spacing). `priors.py` holds the priors, which are uniform or log-uniform, and the gun-phase range [-25°, 45°].

Everything the networks see is normalized to [0, 1]:

- gun phase: by the fixed range
- charge: by the min and max of the first scan of that trajectory
- T0 and the nuisance parameters: by their prior bounds, in log space for the log-uniform ones

`models.py` holds the posterior: a permutation-invariant DeepSet encoder over the (gun phase, charge) points, then a Gaussian-mixture head. Two sizes are used: a small T0-only model and a larger full-parameter model (T0 plus the 10 nuisance parameters), which gives posterior-predictive curves.

## The two variants

| | Vanilla (`train_vanilla.py`) | BSA scan (`train_bsa.py`) |
|---|---|---|
| First measurement | 10-point grid over the full range | 10-point jittered scan over the full range |
| Next measurements | 10 points per round at T0 values sampled from the posterior | 10-point scans over a range set by the T0 posterior quantiles (`bsa.py`) |
| Total | 100 points (9 rounds) | 40 points (4 scans) |
| Models saved | T0 model per round, final T0 and full-parameter models | T0 and full-parameter models after every scan, plus final ones |
| Original run | `two_bunch_full` | `bsa_full_v2` |

The BSA ranges are: scan 1 covers the full range. Even scans run from the 1% T0 quantile up to the current right bound, which starts at 45°. Odd scans cover the 1% to 99% quantile range, and their upper end becomes the new right bound.

Training is the same loop for both. Each round simulates 1M trajectories under the prior, fits by maximum likelihood with Adam and a short warm-up, and refits the models from scratch on the grown cache. The model trained on k scans is the one that places scan k + 1, both in training and at inference. The BSA models are also trained with up to one point per scan dropped, so a scan that comes back a point short is still in distribution.

## Files

| File | What it does |
|---|---|
| `simulator.py`, `priors.py`, `models.py` | Model, priors and normalization, networks |
| `training.py` | Shared training loop, TorchScript tracing, sampling from traced models, plots |
| `bsa.py` | The BSA scan rule, point selection on real data, loading the BSA models, predictive curves |
| `train_vanilla.py` | Vanilla variant |
| `train_bsa.py` | BSA variant |
| `train_full_from_cache.py` | Longer refit of the full-parameter BSA posteriors from the saved caches; the ones trained in `train_bsa.py` were too short for good predictive plots |
| `fit_prior_to_data.py` | Best-fitting prior sample for each recorded scan, used as realistic ground truth |
| `evaluate_bsa.py` | Runs the BSA protocol on the simulator at those best-fit parameters and plots each scan |
| `infer_bsa_real_data.py` | Replays the BSA protocol on recorded scans by picking measured points, then plots the T0 posterior and posterior predictive |
| `train.sbatch` | Slurm job for either training script |

## Running

```bash
source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh
uv pip install -r boed/requirements.txt     # torch, tqdm on top of the analysis env

cd boed
# smoke tests (minutes)
python train_bsa.py     --out_dir runs/bsa_smoke     --n_trajectories 2000 --epochs 2
python train_vanilla.py --out_dir runs/vanilla_smoke --n_trajectories 2000 --epochs 2

# full runs (hours, one GPU)
sbatch train.sbatch bsa     runs/bsa_full_v2
sbatch train.sbatch vanilla runs/two_bunch_full

# BSA evaluation and inference
python train_full_from_cache.py --cache_dir runs/bsa_full_v2/cache --out_dir runs/full_posterior
python fit_prior_to_data.py     --out_dir runs/best_fits
python evaluate_bsa.py          --model_dir runs/bsa_full_v2 --best_fits_dir runs/best_fits
python infer_bsa_real_data.py   --model_dir runs/bsa_full_v2
```

The recorded scans are pickles with `gunphase` (degrees) and `charge_pC` arrays, read by default from `/sdf/group/mli/samklein/schottky/data`.

## Using a trained model

Each `*_traced_*.pt` file is a TorchScript module. It maps a normalized history `(1, T, 1)` gun phases and `(1, T, 1)` charges to the mixture parameters `(means, stds, log_weights)`, for any number of points T. It needs only torch:

```python
model = torch.jit.load("runs/bsa_full_v2/t0_posterior_traced_scan_01_horizon_010.pt")
samples = training.sample_traced(model, xi_norm, y_norm, 1000)   # (1000, 1), T0 in [0, 1]
t0_deg = samples[:, 0] * 70.0 - 25.0
```

Models saved by policy-boed (`outputs/bsa_full_v2`, `outputs/two_bunch_full_cpu`) load here unchanged, both traced and as state dicts.
