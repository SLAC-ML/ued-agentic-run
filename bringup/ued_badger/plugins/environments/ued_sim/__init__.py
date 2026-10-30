"""Badger environment ued_sim: the virtual UED, for rehearsal.

Knobs Sol1, Sol2, XC/YC00-02, XC/YC04 and the sample x/y, bounded by the
safety ranges of the sim setup file; observables from the Andor. preset
stage5 starts after stage 5 (sample out); stage7 at the Bi sample with the
main beam in the Andor through hole and the diffraction settings. The logic
lives in bringup/ued_badger/envcore.py, shared with the real-machine
environment ued.
"""
import os
import sys
from pathlib import Path

from badger import environment
from pydantic import Field

sys.path.insert(0, os.environ.get('UED_BRINGUP_DIR',
                                  str(Path(__file__).resolve().parents[4])))
from ued_badger import common, envcore  # noqa: E402


class Environment(environment.Environment):
    name = 'ued_sim'
    variables = common.knob_bounds('ued_sim')
    observables = list(common.OBSERVABLES)

    n_avg: int = Field(3, description='Andor readings averaged per point')
    settle_s: float = Field(1.0, description='wait after setting knobs [s]')
    seed: int = Field(0, description='simulator noise seed')
    preset: str = Field('stage5', description='stage5 (after the '
                        'collimator, sample out) or stage7 (at the Bi '
                        'sample, main beam in the through hole)')

    def _m(self):
        return envcore.machine(self.name, self.seed, self.preset)

    def get_bounds(self, variable_names):
        bounds = common.knob_bounds(self.name)   # the setup file, fresh
        return {n: bounds[n] for n in variable_names}

    def get_variables(self, variable_names):
        return envcore.get_knobs(self._m(), variable_names)

    def set_variables(self, variable_inputs):
        envcore.set_knobs(self._m(), self.name, variable_inputs,
                          self.settle_s)

    def get_observables(self, observable_names):
        return envcore.observe(self._m(), observable_names, self.n_avg)

    def get_system_states(self):
        return envcore.states(self._m())
