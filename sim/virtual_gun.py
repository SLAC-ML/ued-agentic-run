"""Stand-in for the UED gun RF and its body temperature.

Lets bringup/gun_ramp.py (and later an agent) run the ramp procedure without
the machine. Time is simulated, so a 10-minute ramp runs in well under a
second.

NOT CALIBRATED. Every constant below is a placeholder chosen to stay inside
the 33..37 C window at the operating point; fit them to archived AREQ, AACT
and gun body temperature from past ramps before trusting any timing.
"""
import random

DT = 0.1  # integration step [s]


class VirtualGun:
    names = ('areq', 'aact', 'pfb_enable', 'afb_enable', 'pfb_status',
             'afb_status', 'gun_temp')
    writable = ('areq', 'pfb_enable', 'afb_enable')

    def __init__(self, seed=0, t_water=34.6, heat_per_areq2=5.7,
                 tau_temp_s=90.0, temp_noise=0.02, tau_aact_s=0.5,
                 open_loop_gain=0.97, aact_noise=0.002, fb_min_areq=0.03,
                 faults=()):
        # placeholders: water temp [C], steady RF heating at AREQ=1 [C],
        # thermal time constant, open-loop amplitude error, feedback floor
        self.rng = random.Random(seed)
        self.t = 0.0
        self.t_water = t_water
        self.heat = heat_per_areq2
        self.tau_temp = tau_temp_s
        self.temp_noise = temp_noise
        self.tau_aact = tau_aact_s
        self.open_loop_gain = open_loop_gain
        self.aact_noise = aact_noise
        self.fb_min = fb_min_areq
        # faults: (time_s, kind, value); kinds: 'water_step' [C], 'afb_trip'
        self.faults = sorted(faults)
        self.state = {'areq': 0.0, 'aact': 0.0, 'pfb_enable': 0,
                      'afb_enable': 0, 'temp': t_water}
        self.tripped = False
        self.fb_ok_for = 0.0

    # backend interface used by bringup/gun_ramp.py
    def time(self):
        return self.t

    def get(self, name):
        s = self.state
        if name == 'gun_temp':
            return s['temp'] + self.rng.gauss(0, self.temp_noise)
        if name == 'aact':
            return s['aact'] * (1 + self.rng.gauss(0, self.aact_noise))
        if name in ('pfb_status', 'afb_status'):
            enabled = s['pfb_enable' if name[0] == 'p' else 'afb_enable']
            if name == 'afb_status' and self.tripped:
                return 'Tripped'
            return 'Active' if enabled and self.fb_ok_for >= 0.5 \
                else 'Inactive'
        return s[name]

    def put(self, name, value):
        if name not in self.writable:
            raise KeyError(f'{name} is not writable')
        self.state[name] = value

    def sleep(self, seconds):
        for _ in range(max(1, round(seconds / DT))):
            self._advance(DT)

    def _advance(self, dt):
        s = self.state
        while self.faults and self.faults[0][0] <= self.t:
            _, kind, value = self.faults.pop(0)
            if kind == 'water_step':
                self.t_water += value
            elif kind == 'afb_trip':
                # a tripped loop holds the drive: AACT stops following AREQ
                self.tripped = True
                self.frozen = s['aact']
        closed = s['afb_enable'] and not self.tripped \
            and self.fb_ok_for >= 0.5
        if self.tripped:
            aim = self.frozen
        else:
            aim = s['areq'] if closed else s['areq'] * self.open_loop_gain
        s['aact'] += (aim - s['aact']) * dt / self.tau_aact
        self.fb_ok_for = self.fb_ok_for + dt if s['aact'] >= self.fb_min \
            else 0.0
        t_eq = self.t_water + self.heat * s['aact'] ** 2
        s['temp'] += (t_eq - s['temp']) * dt / self.tau_temp
        self.t += dt
