#!/usr/bin/env python
"""Mock-up run: the ued_tuning MCP server against the virtual UED.

Starts `python -m ued_tuning` as its own process over stdio — the way
Claude Code launches an MCP server — with UED_TUNING_BACKEND=sim, and calls
the eight stage tools in campaign order through an MCP client, with the
checks and automation tools between them. The setup file
(sim/ued_setup_sim.yaml) is copied into the run folder first, so taught
positions saved during the run go to the copy; records go there too. Every
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
import shutil
import sys
import time
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(os.environ.get('AGENTIC_ROOT',
                           '/sdf/group/mli/zhezhang/ued/agentic'))

CAMPAIGN = [
    ('check_beam_prerequisites', {}),
    ('list_positions', {}),
    ('gun_ramp', {}),
    ('schottky_scan', {}),
    ('set_bunch_charge', {'feedback_loop_off': True}),
    ('monitor_charge', {'samples': 5}),
    ('beam_on_screens', {}),
    ('align_collimator', {}),
    ('plan_beam_optimization', {}),
    ('overlap_pump_laser', {}),
    ('tune_sample_position', {'sample': 'bi'}),
    # the operator approves the pattern and the tuned spot becomes 'bi'
    ('save_position', {'name': 'bi', 'note': 'mock-up: stage 7, approved'}),
    ('find_time_zero', {}),
    # stage 8 again with the amortized BOED scan (am_boed). The virtual
    # UED's drop is ~14 %, three times April's: y_scale brings it near the
    # 4.4 % the models were trained on
    ('find_time_zero', {'method': 'boed', 'y_scale': 0.3}),
    # and with the non-amortized BOED (eig_boed): the fallback when the
    # amortized models don't fit the signal
    ('find_time_zero', {'method': 'eig'}),
]


async def main(out):
    out.mkdir(parents=True, exist_ok=True)
    setup = out / 'ued_setup.yaml'
    shutil.copy2(ROOT / 'sim' / 'ued_setup_sim.yaml', setup)
    env = dict(os.environ,
               UED_TUNING_BACKEND='sim',
               UED_SIM_DIR=str(ROOT / 'sim'),
               UED_BRINGUP_DIR=str(ROOT / 'bringup'),
               UED_SETUP_FILE=str(setup),
               UED_RECORDS_DIR=str(out / 'records'),
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
            'areq', 'aact', 'preq', 'gun_uv_throttle', 'collimator',
            'xc04', 'yc04', 'pump_lens_h', 'pump_lens_v', 'pump_hwp',
            'pump_power_meter', 'pump_shutter', 'chamber_light',
            'cam_sample_yag.cross_x', 'cam_sample_yag.cross_y',
            'cam_far_andor.exposure', 'cam_far_andor.gain', 'sample_x',
            'sample_y', 'delay', 'gv240', 'gv272', 'gv280', 'gv295']})
        record['final_state'] = json.loads(state.content[0].text)
    (out / 'results.json').write_text(json.dumps(record, indent=1))
    print('DONE', out, flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path,
                    default=ROOT / 'runs' / 'sim' / time.strftime(
                        'mcp_mockup_%Y%m%d_%H%M%S'))
    asyncio.run(main(ap.parse_args().out))
