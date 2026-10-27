(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('report-data').textContent);
  var NS = 'http://www.w3.org/2000/svg';

  // ---------- theme switch ----------
  var root = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  var label = document.getElementById('theme-label');
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  try {
    var saved = localStorage.getItem('ued-bringup-theme');
    if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
  } catch (e) {}
  function current() {
    var t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return mq && mq.matches ? 'dark' : 'light';
  }
  function sync() {
    var t = current();
    root.classList.toggle('is-dark', t === 'dark');
    label.textContent = t === 'dark' ? 'Dark' : 'Light';
    btn.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  }
  btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('ued-bringup-theme', next); } catch (e) {}
    sync();
  });
  if (mq && mq.addEventListener) mq.addEventListener('change', sync);
  new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  sync();

  // ---------- helpers ----------
  function el(tag, attrs, parent, text) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function lin(d, r) {
    var f = function (v) { return r[0] + (v - d[0]) / (d[1] - d[0]) * (r[1] - r[0]); };
    f.inv = function (p) { return d[0] + (p - r[0]) / (r[1] - r[0]) * (d[1] - d[0]); };
    return f;
  }
  function ticks(d, n) {
    var span = d[1] - d[0], raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var e = raw / mag, step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
    var out = [], v = Math.ceil(d[0] / step - 1e-9) * step;
    for (; v <= d[1] + step * 1e-6; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return out;
  }
  function fmtNum(v, dp) { var s = v.toFixed(dp); return s.replace('-', '−'); }
  function tip(host) {
    var t = document.createElement('div'); t.className = 'tip'; t.hidden = true; host.appendChild(t); return t;
  }
  function placeTip(t, host, px, py) {
    var w = host.clientWidth, tw = t.offsetWidth;
    var left = px + 14 + tw > w ? px - 14 - tw : px + 14;
    t.style.left = Math.max(0, left) + 'px';
    t.style.top = Math.max(0, py - 10) + 'px';
  }
  var SER = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'];

  function legend(id, names) {
    var host = document.getElementById(id);
    names.forEach(function (n, i) {
      var s = document.createElement('span'), sw = document.createElement('i');
      sw.style.background = SER[i]; s.appendChild(sw); s.appendChild(document.createTextNode(n)); host.appendChild(s);
    });
  }

  // ---------- line chart ----------
  function lineChart(id, o) {
    var host = document.getElementById(id);
    var W = 560, H = o.height || 230, m = { l: 62, r: 16, t: 12, b: 40 };
    var xs = [], ys = [];
    o.series.forEach(function (s) {
      s.x.forEach(function (v, i) { if (isFinite(v) && isFinite(s.y[i])) { xs.push(v); ys.push(s.y[i]); } });
    });
    var xd = o.xd || [Math.min.apply(null, xs), Math.max.apply(null, xs)];
    var yd = o.yd || (function () {
      var a = Math.min.apply(null, ys), b = Math.max.apply(null, ys), p = (b - a) * 0.06 || 1;
      return [a - p, b + p];
    })();
    var X = lin(xd, [m.l, W - m.r]), Y = lin(yd, [H - m.b, m.t]);
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': o.aria });
    ticks(yd, 5).forEach(function (v) {
      el('line', { 'class': 'grid-l', x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, svg);
      el('text', { 'class': 'ax-t', x: m.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, svg, o.fy(v));
    });
    ticks(xd, 6).forEach(function (v) {
      el('line', { 'class': 'base-l', x1: X(v), x2: X(v), y1: H - m.b, y2: H - m.b + 4 }, svg);
      el('text', { 'class': 'ax-t', x: X(v), y: H - m.b + 17, 'text-anchor': 'middle' }, svg, o.fx(v));
    });
    el('line', { 'class': 'base-l', x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, svg);
    el('text', { 'class': 'ax-l', x: (m.l + W - m.r) / 2, y: H - 4, 'text-anchor': 'middle' }, svg, o.xl);
    el('text', { 'class': 'ax-l', x: 0, y: 0, 'text-anchor': 'middle', transform: 'translate(13 ' + ((m.t + H - m.b) / 2) + ') rotate(-90)' }, svg, o.yl);
    (o.hlines || []).forEach(function (h) {
      el('line', { 'class': 'ref-l', x1: m.l, x2: W - m.r, y1: Y(h.y), y2: Y(h.y) }, svg);
      if (h.t) el('text', { 'class': 'ref-t', x: W - m.r - 2, y: Y(h.y) - 4, 'text-anchor': 'end' }, svg, h.t);
    });
    (o.vlines || []).forEach(function (v) {
      el('line', { 'class': 'ref-l', x1: X(v.x), x2: X(v.x), y1: m.t, y2: H - m.b }, svg);
      if (v.t) el('text', { 'class': 'ref-t', x: X(v.x) - 4, y: m.t + 10, 'text-anchor': 'end' }, svg, v.t);
    });
    o.series.forEach(function (s, k) {
      var d = '', pen = false;
      s.x.forEach(function (v, i) {
        var y = s.y[i];
        if (!isFinite(v) || !isFinite(y)) { pen = false; return; }
        d += (pen ? 'L' : 'M') + X(v).toFixed(1) + ' ' + Y(y).toFixed(1); pen = true;
      });
      if (!s.nolink) el('path', { 'class': 'ln c' + (k + 1), d: d }, svg);
      if (o.markers && !s.nomark) s.x.forEach(function (v, i) {
        if (isFinite(s.y[i])) el('circle', { 'class': 'mk f' + (k + 1), cx: X(v), cy: Y(s.y[i]), r: 4 }, svg);
      });
    });
    var xh = el('line', { 'class': 'xh', y1: m.t, y2: H - m.b, visibility: 'hidden' }, svg);
    var dots = o.series.map(function (s, k) { return el('circle', { 'class': 'mk f' + (k + 1), r: 4.5, visibility: 'hidden' }, svg); });
    var hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
    host.appendChild(svg);
    var t = tip(host);
    function nearest(s, xv) {
      var best = -1, bd = Infinity;
      for (var i = 0; i < s.x.length; i++) {
        if (!isFinite(s.y[i])) continue;
        var dd = Math.abs(s.x[i] - xv); if (dd < bd) { bd = dd; best = i; }
      }
      return best;
    }
    function move(ev) {
      var r = svg.getBoundingClientRect(), sc = W / r.width;
      var xv = X.inv((ev.clientX - r.left) * sc);
      // snap to the data point nearest the pointer, in whichever series has it
      var ref = null;
      o.series.forEach(function (s) {
        var i = nearest(s, xv);
        if (i >= 0 && (ref === null || Math.abs(s.x[i] - xv) < Math.abs(ref - xv))) ref = s.x[i];
      });
      if (ref === null) return;
      var html = '<b>' + o.tx(ref) + '</b>';
      o.series.forEach(function (s, k) {
        var i = nearest(s, ref);
        var ok = i >= 0 && Math.abs(s.x[i] - ref) <= (o.snap || Infinity);
        dots[k].setAttribute('visibility', ok ? 'visible' : 'hidden');
        if (!ok) return;
        dots[k].setAttribute('cx', X(s.x[i])); dots[k].setAttribute('cy', Y(s.y[i]));
        html += '<br><i style="background:' + SER[k] + '"></i>' + (s.name ? s.name + ': ' : '') + o.ty(s.y[i]);
      });
      xh.setAttribute('x1', X(ref)); xh.setAttribute('x2', X(ref)); xh.setAttribute('visibility', 'visible');
      t.innerHTML = html; t.hidden = false;
      placeTip(t, host, (X(ref)) / sc, (ev.clientY - r.top));
    }
    function leave() { t.hidden = true; xh.setAttribute('visibility', 'hidden'); dots.forEach(function (d) { d.setAttribute('visibility', 'hidden'); }); }
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', leave);
  }

  function dur(s) {
    if (s < 1) return '<1 s';
    if (s < 90) return Math.round(s) + ' s';
    return (s / 60).toFixed(s < 600 ? 1 : 0) + ' min';
  }

