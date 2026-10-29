"""Badger environment ued: the real UED, read-only.

Knobs Sol1, Sol2, XC/YC00-02 and XC/YC04, bounded by the safety ranges of
the live setup file; observables from the Andor spot. Reads go through
the CA settings and PV prefix (bringup/pv_access.py); every write is
refused (ued_tuning's EpicsBackend). The logic is in ued_badger/envcore.py.
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
    name = 'ued'
    variables = common.knob_bounds('ued')
    observables = list(common.OBSERVABLES)

    n_avg: int = Field(3, description='Andor readings averaged per point')
    settle_s: float = Field(1.0, description='wait after setting knobs [s]')

    def _m(self):
        return envcore.machine(self.name)

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
