  // ---------- charts ----------
  function erf(x) {   // Abramowitz-Stegun 7.1.26, |error| < 1.5e-7
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
  }
  function col(pts, k) { return pts.map(function (p) { return p[k]; }); }

  // stage 2: scope charge vs phase over the whole PREQ range
  var S2 = D.schottky;
  var qmax = Math.max.apply(null, col(S2.coarse, 1).concat(col(S2.fine, 1)));
  legend('sch-legend', ['coarse, 5° steps', 'fine, 0.5° steps']);
  lineChart('ch-schottky', {
    series: [{ name: 'coarse', x: col(S2.coarse, 0), y: col(S2.coarse, 1) },
             { name: 'fine', x: col(S2.fine, 0), y: col(S2.fine, 1) }],
    xd: [-180, 180], yd: [-3, Math.ceil((qmax + 2) / 5) * 5], markers: true, snap: 1.5,
    hlines: [{ y: S2.threshold, t: 'threshold ' + S2.threshold.toFixed(1) + ' fC' }],
    vlines: [{ x: S2.emission, t: 'emission ' + S2.emission.toFixed(1) + '°' }, { x: S2.operating, t: 'PREQ' }],
    xl: 'gun phase PREQ (deg)', yl: 'scope charge (fC)', fx: function (v) { return v.toFixed(0); }, fy: function (v) { return v.toFixed(0); },
    tx: function (v) { return 'PREQ ' + fmtNum(v, 1) + '°'; }, ty: function (v) { return fmtNum(v, 2) + ' fC'; },
    aria: 'Scope charge against gun phase, coarse and fine scans, with the detection threshold, the emission phase and the operating phase'
  });

  // stage 5: Andor counts vs collimator motor position
  var C5 = D.collimator;
  var cmax = Math.max.apply(null, C5.scan_total.concat(C5.fine_total)) / 1000;
  legend('col-legend', ['scan, 0.1 mm steps', 'fine, 0.02 mm steps']);
  var cv = [{ x: C5.collimator_mm, t: 'set ' + C5.collimator_mm.toFixed(2) }];
  if (C5.ideal !== null) cv.push({ x: C5.ideal });
  lineChart('ch-coll', {
    series: [{ name: 'scan', x: C5.scan_mm, y: C5.scan_total.map(function (v) { return v / 1000; }) },
             { name: 'fine', x: C5.fine_mm, y: C5.fine_total.map(function (v) { return v / 1000; }) }],
    xd: [C5.scan_mm[0] - 0.05, C5.scan_mm[C5.scan_mm.length - 1] + 0.05], yd: [0, Math.ceil(cmax * 1.15 / 50) * 50],
    markers: true, snap: 0.012, vlines: cv,
    xl: 'collimator motor (mm)', yl: 'Andor counts (thousands)', fx: function (v) { return v.toFixed(1); }, fy: function (v) { return v.toFixed(0); },
    tx: function (v) { return 'collimator ' + v.toFixed(2) + ' mm'; }, ty: function (v) { return v.toFixed(1) + 'k'; },
    aria: 'Andor counts against the collimator motor position, coarse and fine scans'
  });
  var ins = C5.insertion.map(function (p) { return p[0].toFixed(0) + ' mm: ' + Math.round(p[1]) + ' counts'; }).join(', ');
  document.getElementById('note-coll').textContent = 'Inserting the collimator (' + ins + '; ' +
    (C5.andor_counts_out / 1e6).toFixed(2) + ' million with it out) shows what Fuhao described: ' +
    'blocked as the plate comes in, then the beam reappears, cut, near the hole. The motor puts the hole on the beam, which sits off-axis ' +
    'in the simulator (a hidden cathode-spot offset), so the best position is ' + C5.collimator_mm.toFixed(2) + ' mm, not 90.00.';

  // stage 8: time zero, the last zoomed scan and its fit
  var T0 = D.t0, L = T0.levels[T0.levels.length - 1];
  var fx0 = T0.fine[0][0], fx1 = T0.fine[T0.fine.length - 1][0], fit = { x: [], y: [] };
  for (var i = 0; i <= 120; i++) {
    var dv = fx0 + (fx1 - fx0) * i / 120;
    fit.x.push(dv); fit.y.push(L.i0 * (1 - L.drop * 0.5 * (1 + erf((dv - L.t0_mm) / (Math.SQRT2 * L.width_mm)))));
  }
  legend('t0-legend', ['scan, ±' + (L.span_mm >= 0.1 ? L.span_mm + ' mm' : Math.round(L.span_mm * 1000) + ' µm') + ' (level ' + T0.levels.length + ')', 'erf fit']);
  lineChart('ch-t0', {
    series: [{ name: 'scan', x: col(T0.fine, 0), y: col(T0.fine, 1), nolink: true },
             { name: 'fit', x: fit.x, y: fit.y, nomark: true }],
    xd: [fx0, fx1], yd: [0.83, 1.02], markers: true, snap: 0.0012,
    vlines: [{ x: T0.t0, t: 't₀ ' + T0.t0.toFixed(4) + ' mm' }],
    xl: 'delay stage (mm)', yl: 'Bragg signal (pump off = 1)', fx: function (v) { return v.toFixed(2); }, fy: function (v) { return v.toFixed(2); },
    tx: function (v) { return 'delay ' + v.toFixed(4) + ' mm'; }, ty: function (v) { return v.toFixed(3); },
    aria: 'Bragg-peak signal against delay around t0, with the erf fit'
  });

  // convergence: error / tolerance, log scale. Charge to 10 fC (+/-1 fC),
  // laser to the cross (3 px), main beam into the through hole (30 px radius;
  // once in, the beam vanishes, so its last point is the simulator's truth).
  var ovl = D.overlap.map(function (s) { return Math.hypot(s.error_px[0], s.error_px[1]) / 3; });
  ovl.push(D.overlap_final_px / 3);
  var hole = D.hole.history.map(function (s) { return Math.hypot(s.error_px[0], s.error_px[1]) / 30; });
  var ht = D.truth.andor_main_beam_minus_hole_px;
  if (ht) hole.push(Math.hypot(ht[0], ht[1]) / 30);
  var conv = [
    { name: 'charge (stage 3)', e: D.charge.map(function (p) { return Math.abs(p[1] - 10) / 1; }) },
    { name: 'laser on the cross (stage 6)', e: ovl },
    { name: 'through hole (stage 7)', e: hole }
  ];
  legend('conv-legend', conv.map(function (c) { return c.name; }));
  lineChart('ch-conv', {
    series: conv.map(function (c) { return { name: c.name, x: c.e.map(function (_, i) { return i + 1; }), y: c.e.map(function (v) { return Math.log10(Math.max(v, 0.01)); }) }; }),
    xd: [0.8, Math.max.apply(null, conv.map(function (c) { return c.e.length; })) + 0.2], yd: [-2.2, 2.4], markers: true, snap: 0.3,
    hlines: [{ y: 0, t: 'tolerance' }],
    xl: 'measurement', yl: 'error ÷ tolerance', fx: function (v) { return Math.abs(v - Math.round(v)) < 1e-6 ? v.toFixed(0) : ''; },
    fy: function (v) { return Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.pow(10, Math.round(v))) : ''; },
    tx: function (v) { return 'measurement ' + v; }, ty: function (v) { return Math.pow(10, v).toFixed(2) + '×'; },
    aria: 'Error over tolerance per measurement for the charge, laser overlap and through-hole loops'
  });
})();
