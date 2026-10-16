#!/usr/bin/env python
"""Read-only check: the ued_tuning MCP server against the real machine.

Starts `python -m ued_tuning` over stdio with UED_TUNING_BACKEND=epics, as
the agent would, reads every logical channel through `machine_read`, then
calls each stage tool. The EPICS backend refuses every write before any
EPICS call, so each stage stops at its first write; the check records how
far it got. Nothing is ever written to a PV.

Run on ued-daq with the UED build's Python (it has fastmcp and pyepics) and
the CA address list from ued_setup.sh, which ~/.bashrc sets there:
    PY=/sdf/group/mli/zhezhang/OspreyDeployments/UED/build/.venv/bin/python
    bash -ic "$PY mcp_readonly_check.py [--out FILE]"
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

HERE = Path(__file__).resolve().parent
STAGES = ['gun_ramp', 'schottky_scan', 'set_bunch_charge', 'beam_on_screens',
          'align_collimator', 'overlap_pump_laser', 'tune_sample_position',
          'find_time_zero']


async def main(out):
    env = dict(os.environ, UED_TUNING_BACKEND='epics',
               PYTHONPATH=str(HERE))
    transport = StdioTransport(command=sys.executable,
                               args=['-m', 'ued_tuning'], env=env,
                               cwd=str(HERE))
    record = {'started': time.strftime('%Y-%m-%d %H:%M:%S'),
              'host': os.uname().nodename,
              'ca_addr_list': os.environ.get('EPICS_CA_ADDR_LIST')}
    async with Client(transport, timeout=600) as c:
        async def call(tool, args=None):
            res = await c.call_tool(tool, args or {})
            return json.loads(res.content[0].text)

        record['info'] = await call('ued_tuning_info')
        channels = await call('machine_channels')
        record['channels'] = channels
        t0 = time.time()
        record['reads'] = (await call('machine_read', {
            'names': [ch['name'] for ch in channels]}))['values']
        record['read_wall_s'] = round(time.time() - t0, 1)
        record['stages'] = {}
        for tool in STAGES:
            r = await call(tool)
            record['stages'][tool] = {'ok': r['ok'], 'reason': r['reason'],
                                      'wall_s': r.get('wall_s')}
            print(f'{tool:22s} {r["reason"]}', flush=True)
    answered = sum(not isinstance(v, dict) for v in record['reads'].values())
    print(f'{answered} of {len(record["reads"])} channels answered',
          flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1))
    print('wrote', out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path, default=Path(
        '/sdf/group/mli/zhezhang/ued/agentic/runs/epics') / time.strftime(
        'readonly_check_%Y%m%d_%H%M%S.json'))
    asyncio.run(main(ap.parse_args().out))
