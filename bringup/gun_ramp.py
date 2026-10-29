"""Gun RF ramp-up, ported from ramp_rf.py (england@slac.stanford.edu, 2026).

Same procedure as the original: set AREQ to 0.05, enable the phase and
amplitude feedbacks, then step AREQ up to the target in 300 steps of 2 s,
holding before each step until the gun body temperature is in 33..37 C and
aborting (AREQ -> 0) after 10 out-of-range readings in a row.

Added on top (commented out or absent in the original):
  - the feedbacks must report Active before the ramp and at every step;
  - the amplitude readback must track the setpoint during the ramp. AACT is
    in kV and AREQ is dimensionless on the real machine, so the check is on
    their ratio: calibrated over the first steps, then held within
    readback_tol.

The procedure talks to a backend with get(name), put(name, value) and
sleep(seconds): the virtual UED, or the read-only EPICS backend, which
refuses the first write. Driving the real gun needs an explicit go-ahead.

Operator preconditions (not checked here, from the UED notes): AREQ is 0 on
the operator panel, the modulator is in TRIG with the HV at full voltage
(VoltSet = 980 V), and readbacks match the 0.05 setpoint.
"""
from dataclasses import dataclass, field
from typing import List

# Machine PVs behind the backend names, for reference only: the live map
# is ued_tuning/channels.py. The gun is on the TS8 klystron KY03
# (since 2026-10-28; TS1/KY01 is offline).
PVS = {
    'areq': 'SIOC:AS01:KY03:0:AREQ',          # amplitude setpoint
    'pfb_enable': 'SIOC:AS01:KY03:0:PFBENB',  # phase feedback on
    'afb_enable': 'SIOC:AS01:KY03:0:AFBENB',  # amplitude feedback on
    'pfb_status': 'SIOC:AS01:KY03:0:PFBST',
    'afb_status': 'SIOC:AS01:KY03:0:AFBST',
    'gun_temp': 'APC:AS01:TM01:M2_CH2_SPARE',  # gun body temperature [C]
    'aact': 'SIOC:AS01:KY03:0:AACT_AVGNT',    # amplitude readback (avg, kV)
}

AREQ_MAX = 0.53


@dataclass
class RampConfig:
    target: float
    start: float = 0.05
    n_steps: int = 300
    dwell_s: float = 2.0
    temp_min: float = 33.0
    temp_max: float = 37.0
    max_temp_fails: int = 10
    fb_settle_s: float = 1.0
    readback_tol: float = 0.05     # relative drift of AACT/AREQ (added)
    calib_steps: int = 3           # steps that calibrate AACT/AREQ
    max_readback_fails: int = 5


@dataclass
class RampResult:
    ok: bool
    reason: str
    final_areq: float
    trace: List[dict] = field(default_factory=list)


def ramp(backend, cfg: RampConfig) -> RampResult:
    if not 0.0 <= cfg.target <= AREQ_MAX:
        raise ValueError(f'target must be in 0..{AREQ_MAX}')
    trace = []

    def log(step, event=''):
        trace.append({'t': backend.time(), 'step': step,
                      'areq': backend.get('areq'),
                      'aact': backend.get('aact'),
                      'temp': backend.get('gun_temp'), 'event': event})

    def abort(step, reason):
        backend.put('areq', 0.0)
        log(step, 'abort: ' + reason)
        return RampResult(False, reason, 0.0, trace)

    backend.put('areq', cfg.start)
    backend.put('pfb_enable', 1)
    backend.put('afb_enable', 1)
    backend.sleep(cfg.fb_settle_s)
    log(0, 'feedbacks enabled')
    for fb in ('pfb_status', 'afb_status'):
        if backend.get(fb) != 'Active':
            return abort(0, f'{fb} is {backend.get(fb)!r}, expected Active')

    step_size = (cfg.target - cfg.start) / (cfg.n_steps - 1)
    temp_fails = readback_fails = 0
    ratios, k0 = [], None           # AACT/AREQ, its calibrated value
    for step in range(1, cfg.n_steps + 1):
        while True:
            temp = backend.get('gun_temp')
            if cfg.temp_min <= temp <= cfg.temp_max:
                temp_fails = 0
                break
            temp_fails += 1
            log(step, f'temperature {temp:.2f} C out of range, waiting')
            if temp_fails >= cfg.max_temp_fails:
                return abort(step, 'temperature out of range '
                             f'{cfg.max_temp_fails} times in a row')
            backend.sleep(cfg.dwell_s)

        for fb in ('pfb_status', 'afb_status'):
            if backend.get(fb) != 'Active':
                return abort(step, f'{fb} went {backend.get(fb)!r}')

        areq, aact = backend.get('areq'), backend.get('aact')
        if areq > 0 and k0 is None:
            ratios.append(aact / areq)
            if len(ratios) == cfg.calib_steps:
                k0 = sorted(ratios)[len(ratios) // 2]
                if not k0 > 0:
                    return abort(step, f'no amplitude readback (AACT '
                                 f'{aact:.3g} at AREQ {areq:.3f})')
        elif areq > 0 and abs(aact / areq - k0) > cfg.readback_tol * k0:
            readback_fails += 1
            if readback_fails >= cfg.max_readback_fails:
                return abort(step, f'readback {aact:.4g} not tracking '
                             f'setpoint {areq:.3f} (AACT/AREQ '
                             f'{aact / areq:.4g}, calibrated {k0:.4g})')
        else:
            readback_fails = 0

        backend.put('areq', cfg.start + (step - 1) * step_size)
        backend.sleep(cfg.dwell_s)
        log(step)

    return RampResult(True, 'reached target', backend.get('areq'), trace)
