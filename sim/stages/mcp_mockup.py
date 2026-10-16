#!/usr/bin/env python
"""Mock-up run: the ued_tuning MCP server against the virtual UED.

Starts `python -m ued_tuning` as its own process over stdio — the way
Claude Code launches an MCP server — with UED_TUNING_BACKEND=sim, and calls
the eight stage tools in campaign order through an MCP client. Every
request, response and wall time is recorded; at the end the sim-only
`sim_truth` tool says how close the tuned machine is to the hidden truth.

Run on S3DF (iana) with the UED build's Python, which has fastmcp:
    source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh
    PY=/sdf/group/mli/zhezhang/OspreyDeployments/UED/build/.venv/bin/python
    $PY mcp_mockup.py [--out DIR]
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

ROOT = Path(os.environ.get('AGENTIC_ROOT',
                           '/sdf/group/mli/zhezhang/ued/agentic'))

CAMPAIGN = [
    ('gun_ramp', {}),
    ('schottky_scan', {}),
    ('set_bunch_charge', {'target_fC': 10.0}),
    ('beam_on_screens', {}),
    ('align_collimator', {}),
    ('overlap_pump_laser', {}),
    ('tune_sample_position', {'sample': 'bi'}),
    ('find_time_zero', {}),
]


async def main(out):
    env = dict(os.environ,
               UED_TUNING_BACKEND='sim',
               UED_SIM_DIR=str(ROOT / 'sim'),
               UED_BRINGUP_DIR=str(ROOT / 'bringup'),
               PYTHONPATH=str(ROOT / 'bringup'))
    transport = StdioTransport(command=sys.executable,
                               args=['-m', 'ued_tuning'], env=env,
                               cwd=str(ROOT / 'sim'))
    record = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'calls': []}
    async with Client(transport, timeout=3600) as c:
        tools = await c.list_tools()
        record['tools'] = [{'name': t.name, 'params': list(
            (t.inputSchema or {}).get('properties', {}))} for t in tools]
        info = json.loads((await c.call_tool('ued_tuning_info', {}))
                          .content[0].text)
        record['info'] = info
        print('tools:', [t.name for t in tools], flush=True)
        for name, args in CAMPAIGN:
            t0 = time.time()
            res = await c.call_tool(name, args)
            data = json.loads(res.content[0].text)
            record['calls'].append({'tool': name, 'args': args,
                                    'client_wall_s': round(time.time() - t0,
                                                           1),
                                    'response': data})
            print(f"{name:22s} ok={data.get('ok')} "
                  f"accepted={data.get('accepted')} | {data.get('reason')} "
                  f"| {time.time() - t0:.0f} s", flush=True)
        record['truth'] = json.loads((await c.call_tool('sim_truth', {}))
                                     .content[0].text)
        state = await c.call_tool('machine_read', {'names': [
            'areq', 'aact', 'preq', 'gun_uv_throttle', 'fc_charge',
            'xc00', 'yc00', 'xc01', 'yc01', 'pump_lens_h', 'pump_lens_v',
            'pump_power_meter', 'chamber_light', 'cam_sample_yag.cross_x',
            'cam_sample_yag.cross_y', 'sample_x', 'sample_y', 'delay']})
        record['final_state'] = json.loads(state.content[0].text)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results.json').write_text(json.dumps(record, indent=1))
    print('DONE', out, flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path,
                    default=ROOT / 'runs' / 'sim' / time.strftime(
                        'mcp_mockup_%Y%m%d_%H%M%S'))
    asyncio.run(main(ap.parse_args().out))
