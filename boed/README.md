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
| `ued_t0.py` | One BSA step for the UED tools: the T0 posterior after the scans so far and the next scan (JSON in, JSON out) |

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

## In the UED bring-up tools

Stage 2 of `ued_tuning` (`schottky_scan`, [bringup/README.md](../bringup/README.md)) runs the BSA protocol with `method='bsa'`, on the `bsa_full_v2` models. The agent's Python has no torch, so after every scan the stage runs `ued_t0.py` in `UED_BOED_PYTHON` (default: the AgenticOpt venv on S3DF) with the points so far, and gets back the T0 posterior and the next scan. The models are a copy of `policy-boed/outputs/bsa_full_v2` in `/sdf/group/mli/zhezhang/ued/agentic/boed/models/bsa_full_v2` (`UED_BOED_MODEL_DIR`), so they don't change under the tools.

The model's frame is placed on the gun phase setpoint: `PREQ = centre + x`, with `x` in [T_MIN, T_MAX] and the charge rising with `x` past T0, as on UED. The centre is the edge of the stage's coarse 5° scan, or `onset_guess_deg` + 8°. The scan points are plain grids (no jitter). The stage takes the posterior median as the emission phase. It stops for an operator, and puts PREQ back, if the 98 % interval is wider than `bsa_max_width_deg` (4°), or if the measured charge disagrees with it. The second check requires the points 4–12° below T0 to sit under the scope's detection threshold and the points 4–12° above it to sit over it.

Checked on 2026-10-29:

- On the first three recorded scans, replayed through `ued_t0.py` with interpolated charges: the 98 % interval after four scans was 2–2.5° wide. Each step takes ~4.5 s on CPU (load plus inference), ~22 s per run.
- On the virtual UED (`sim/virtual_ued.py`, emission at PREQ 122.1° by the scope-threshold definition), centred on the coarse edge: T0 120.5° and 121.0°, against the grid method's 121.8° and 122.5°. T0 marks where the rise starts, about 1.5° before the threshold crossing. Interpolated from the BSA points, the crossing came out at 121.9°.
- Window placement matters. Centred 0–15° above the onset, it gave the right phase. Centred 6–12° below it, it gave wrong phases (101–114°), and all four were refused by the two checks. Hence the +8° shift for a guess.
- With the shift, guesses from 10° below to 7° above the onset ran 40 points, against 93 for the grid. Of 12 runs, 9 were accepted and 3 refused (one by the charge check, two by the interval width), with no wrong phase accepted. Accepted T0s were 1.3–3.1° before the threshold crossing, and the crossing interpolated from the BSA points was within 0.2–2° of it. Each run took 22–78 s of wall time on iana.

The virtual UED's charge-vs-phase curve is our own model, not a recorded UED scan. How the protocol does on a real UED Schottky scan is still to be seen.

