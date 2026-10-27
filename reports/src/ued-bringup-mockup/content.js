  // ---------- page content ----------
  var ST = D.stages;
  var STATUS_CLASS = { CONFIRMED: 'ok', LIKELY: 'ok', CANDIDATE: 'warn', UNMAPPED: 'bad', NO_ACCESS: 'bad', SIM_ONLY: 'bad' };
  var INFO = [
    { key: 'gun_ramp', n: 1, name: 'Gun ramp-up', sim: 'Virtual gun: placeholder RF and thermal model',
      real: 'Refused at its first write, closing the pump shutter. Reads the KY01 gun RF (AREQ parked at 0.2, no output) and the gun body temperature.',
      blockers: ['The write route for the gun RF',
                 'AREQ calibration to MV/m; modulator mode and HV PVs (operator confirms today)',
                 'Archived ramps to calibrate the virtual gun'] },
    { key: 'schottky_scan', n: 2, name: 'Schottky scan', sim: 'Analytic Schottky photoemission on a modelled scope CH2 trace (negative pulse, -0.17 mV/fC, the measured noise)',
      real: 'Stops before any write: gate valves not OPEN. Its scope and diagnostic-camera reads work.',
      blockers: ['Diagnostic screen inserted by hand (no PV)',
                 'Scope channel (CH2 vs CH0) and the UDF V/div record',
                 'Emission phase definition (onset at 5σ is assumed)'] },
    { key: 'set_bunch_charge', n: 3, name: 'Pulse charge + UV feedback', sim: 'Analytic: UV throttle transmission x photoemission, on the scope',
      real: "Stops before any write: it waits for the operator to confirm Cameron's UV feedback loop is stopped.",
      blockers: ["Cameron's loop: location, PVs, its full objective",
                 'Throttle safety range (45-60 deg is a placeholder)'] },
    { key: 'beam_on_screens', n: 4, name: 'Beam on YAG & EMCCD', sim: 'GPT beam at each screen + a camera model; the e-beam cross',
      real: 'Stops before any write: gate valves not OPEN. The cameras and the cross read; stats from the images say no beam.',
      blockers: ['Taught yag and andor positions',
                 'Diagnostic screen extracted by hand',
                 'E-beam view gain: 10 or 30'] },
    { key: 'align_collimator', n: 5, name: 'Collimator alignment', sim: 'GPT: the collimator motor moves a 200 um hole across an off-axis beam',
      real: 'Stops before any write: gate valves not OPEN. The collimator reads 0 mm.',
      blockers: ['Collimator safety range and hole positions to confirm',
                 'Who runs the Badger routine: the agent (proposal) or an operator',
                 'Corrector kick per BCTRL unit'] },
    { key: 'overlap_pump_laser', n: 6, name: 'e-beam / laser overlap', sim: 'GPT e-beam at the sample + analytic pump-lens map; HWP energy, power meter and chamber light modelled',
      real: 'Stops before any write: gate valves not OPEN. Lens, HWP and power meter read (the power meter is in).',
      blockers: ['Pump HWP minimum-energy setpoint (laser team)',
                 'Pump steering: lens H/V or SmarAct m7/m8',
                 'Taught yag position'] },
    { key: 'tune_sample_position', n: 7, name: 'Sample-position tuning', sim: 'GPT main beam vs the Andor through hole, diffraction rings, a toy Bi flake with a crack',
      real: 'Stops before any write: gate valves not OPEN. Sample stage and the Andor image read; no pattern score exists.',
      blockers: ['Andor through-hole position and radius',
                 'Taught sample positions',
                 'A pattern score (intensity alone today); operator judgement by design'] },
    { key: 'find_time_zero', n: 8, name: 'Time zero', sim: 'Analytic erf step; width from the GPT bunch length and the pump',
      real: 'Stops before any write: its overlap check finds the gate valves not OPEN.',
      blockers: ['Pump HWP ~2 uJ setpoint (laser group)',
                 'Bragg signal from the LCLS DAQ or the Run 6 BOED script',
                 'Delay mm to fs calibration and sign'] }
  ];
  var rows = document.getElementById('stage-rows');
  INFO.forEach(function (s) {
    var st = ST[s.key];
    var counts = { ok: 0, warn: 0, bad: 0 };
    st.written.forEach(function (w) { counts[STATUS_CLASS[w.status] || 'bad'] += 1; });
    var dots = ['ok', 'warn', 'bad'].filter(function (k) { return counts[k]; }).map(function (k) {
      return '<span class="cnt"><i class="dot ' + k + '"></i>' + counts[k] + '</span>';
    }).join('');
    var list = st.written.map(function (w) {
      return '<li><i class="dot ' + (STATUS_CLASS[w.status] || 'bad') + '"></i><code>' + w.name + '</code> <span class="muted">' +
        (w.pv ? w.pv : 'no PV') + ' · ' + w.status + '</span></li>';
    }).join('');
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="t-stage"><div class="st-name"><span class="n">' + s.n + '</span><div><b>' + s.name + '</b><code>' + s.key + '</code></div></div></td>' +
      '<td class="t-sim">' + s.sim + '</td>' +
      '<td class="t-mock"><span class="pill ' + (st.accepted ? 'ok' : 'bad') + '">' + (st.accepted ? 'accepted' : 'not accepted') + '</span>' +
      '<p>' + D.text[s.key] + '</p><p class="muted small">' + st.n_writes + ' writes · ' + dur(st.machine_s) + ' machine time' + (st.wall_s >= 1 ? ' · ' + dur(st.wall_s) + ' wall' : '') + '</p></td>' +
      '<td class="t-real"><p>' + s.real + '</p><details><summary>' + dots + '<span class="muted small"> ' + st.written.length +
      ' channels written</span></summary><ul class="chans">' + list + '</ul></details></td>' +
      '<td class="t-block"><ul>' + s.blockers.map(function (b) { return '<li>' + b + '</li>'; }).join('') + '</ul></td>';
    rows.appendChild(tr);
  });
  document.getElementById('f-mock').textContent = '8 of 8 stages accepted in one MCP session: ' + D.wall_min +
    ' min wall time, ' + D.truth.stats.gpt_runs + ' GPT runs, ' + D.truth.stats.puts + ' writes to the virtual machine, every one checked against its safety range.';

  // ---------- read-only check on ued-daq ----------
  var E = D.epics;
  function fmtRead(v) {
    if (v === null) return '—';
    if (Array.isArray(v)) return v.length + ' samples';
    if (typeof v === 'number') return Math.abs(v) >= 1e4 ? v.toExponential(2) : String(+v.toFixed(4));
    return String(v);
  }
  var GROUPS = [
    ['vacuum', 'Gate valves', '240 CLOSED, 272 CLOSED, 280 INCONSISTENT, 295 CLOSED: no beam can reach the screens'],
    ['gun_rf', 'Gun RF (KY01)', 'AREQ 0.2 and PREQ -172 deg, feedbacks "Disable", no output; gun body 36 °C'],
    ['laser', 'Lasers', 'UV throttle 50 deg, shutters 0 V, pump HWP 6 deg (near its minimum), power meter in (40 mm)'],
    ['diagnostics', 'Scope', 'CH2 at 1 mV/div and CH0 at 1 V/div read; baseline +3.36 div, no pulse'],
    ['magnets', 'Solenoids', 'Setpoints 0.215 and 3.805; solenoid 1 "Turned Off", solenoid 2 "PS Tripped" (10-16)'],
    ['beamline', 'Inserters, light', 'Collimator 0 mm, chamber light state 0; the diagnostic-screen inserter has no PV'],
    ['sample', 'Sample stage', 'XPS-11 X -21.85, Y -7.6, Z 0.1, pitch -10.95, yaw -32.5; pattern quality has no PV'],
    ['pump_probe', 'Pump-probe', 'Long delay 141.36 mm; the Bragg signal has no PV'],
    ['camera', 'Cameras', 'Exposure, gain, the e-beam cross and Andor acquisition read; stats from the images say no beam'],
    ['correctors', 'Correctors', 'XC/YC00-04 BCTRL read (XC00 -145.6, YC00 -35.0); XC/YC05 has no PV']
  ];
  var byGroup = {};
  E.channels.forEach(function (c) { (byGroup[c.group] = byGroup[c.group] || []).push(c); });
  var gt = '<thead><tr><th>Group</th><th class="num">Answered</th><th>Status</th><th>What it read on 2026-10-21</th></tr></thead><tbody>';
  GROUPS.forEach(function (g) {
    var cs = byGroup[g[0]] || [], ok = 0, counts = { ok: 0, warn: 0, bad: 0 };
    cs.forEach(function (c) {
      var v = E.reads[c.name];
      if (!(v && typeof v === 'object' && !Array.isArray(v))) ok += 1;
      counts[STATUS_CLASS[c.status] || 'bad'] += 1;
    });
    var dots = ['ok', 'warn', 'bad'].filter(function (k) { return counts[k]; }).map(function (k) {
      return '<span class="cnt"><i class="dot ' + k + '"></i>' + counts[k] + '</span>';
    }).join(' ');
    gt += '<tr><td><b>' + g[1] + '</b></td><td class="num">' + ok + ' / ' + cs.length + '</td><td class="nowrap">' + dots + '</td><td>' + g[2] + '</td></tr>';
  });
  document.getElementById('epics-groups').innerHTML = gt + '</tbody>';

  var STAGE_NAMES = {};
  INFO.forEach(function (s) { STAGE_NAMES[s.key] = s.n + ' · ' + s.name; });
  var tt = '<thead><tr><th>Stage tool</th><th>Where it stopped</th></tr></thead><tbody>';
  Object.keys(E.stages).forEach(function (k) {
    var s = E.stages[k], w = /refused put (\S+?):/.exec(s.reason), txt;
    if (w) txt = 'at its first write, <code>' + w[1] + '</code>, refused before any EPICS call';
    else if (/gate valves not all OPEN/.test(s.reason)) txt = 'before any write: the gate valves are not all OPEN';
    else if (/feedback loop/.test(s.reason)) txt = "before any write: waits for the operator to confirm Cameron's UV feedback loop is stopped";
    else txt = s.reason;
    tt += '<tr><td>' + STAGE_NAMES[k] + '</td><td>' + txt + '</td></tr>';
  });
  document.getElementById('epics-stages').innerHTML = tt + '</tbody>';

  var ct = '<thead><tr><th>Channel</th><th>PV</th><th>Read</th><th>Status</th></tr></thead><tbody>';
  E.channels.forEach(function (c) {
    var v = E.reads[c.name], err = v && typeof v === 'object' && !Array.isArray(v);
    var txt = err ? 'no PV' : fmtRead(v) + (c.pv_units ? ' <span class="muted">(' + c.pv_units + ')</span>' : '');
    ct += '<tr><td><code>' + c.name + '</code></td><td><code class="muted">' + (c.pv || '—') + '</code></td><td class="' +
      (err ? 'muted' : 'val') + '">' + txt + '</td><td class="nowrap"><i class="dot ' + (STATUS_CLASS[c.status] || 'bad') + '"></i> ' + c.status + '</td></tr>';
  });
  document.getElementById('epics-all').innerHTML = ct + '</tbody>';
  document.getElementById('epics-count').textContent = E.answered + ' of ' + E.channels.length;

  // ---------- what still stands in the way ----------
  var CROSS = [
    ['Write path', 'all stages', 'The agent is read-only on ued-daq by design, and every stage writes. Pick the route: Badger routines an operator approves (the proposal), or MCP writes behind approval and the safety ranges the tools already check. The gun RF and magnets are a separate decision.', ''],
    ['Setup values', 'stages 4-8', 'The taught positions (yag, andor, bi, si), the pump HWP setpoints for minimum energy and ~2 uJ, and the Andor through hole are empty in the setup file. A stage that needs one stops and names it.', ''],
    ['Safety ranges', 'all writes', 'Seeded 2026-10-21 from the motors\' soft limits and the magnets\' drive limits, and checked before every write. The pump HWP and UV throttle ranges are placeholders: their IOCs allow +/-1e6 and +/-180.', 'done'],
    ['Operator steps', 'stages 2-4', 'The diagnostic screen has no PV, so inserting and extracting it is an operator step. Cameron\'s UV feedback loop is a GUI the operator teaches after stage 3.', ''],
    ['Accelerator access', 'reads solved', 'Gun RF (KY01), solenoids, quads and correctors read from ued-daq and in the deployed agent.', 'done'],
    ['Detector-derived signals', 'stages 7, 8', 'The Andor image reads over CA, so a pattern score and Bragg-peak ROIs can be computed; neither exists yet. Time zero on the real machine runs in the LCLS DAQ or the Run 6 BOED script.', '']
  ];
  document.getElementById('cross').innerHTML = CROSS.map(function (c) {
    return '<div class="box' + (c[3] ? ' ' + c[3] : '') + '"><h4>' + c[0] + '<span class="chip">' + c[1] + '</span></h4><p>' + c[2] + '</p></div>';
  }).join('');

