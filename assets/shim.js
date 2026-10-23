/* A small stand-in for the claude.ai dashboard runtime, so the same page code runs from
   data/data.json on any web server. Same `dash` API the page uses: data, onData, calc,
   loader (ignored: data.json is already shaped), colors, params/setParams (page state such as
   the date range; setting them recomputes the calcs). */
(function () {
  const store = {};          // dataset id -> rows
  const calcs = [];          // [{id, inputs, fn}]
  const cbs = [];
  let status = 'loading';
  let generatedAt = null;
  let params = {};

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const colors = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6', '--series-7', '--series-8'].map((n) => `var(${n})`);

  function computeCalcs() {
    calcs.forEach((c) => {
      try {
        const args = c.inputs.map((i) => store[i] || []);
        store[c.id] = c.fn(...args);
      } catch (e) {
        console.error('calc failed:', c.id, e);
        store[c.id] = [];
      }
    });
  }

  let running = false;
  function fire() {
    if (running) return;
    running = true;
    cbs.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    running = false;
  }

  window.dash = {
    colors,
    data(id) {
      if (status !== 'ok') return { status, data: [], columns: [], refreshing: false, meta: [], message: status === 'error' ? 'data.json did not load' : undefined };
      const d = store[id];
      if (d === undefined) return { status: 'missing', data: [], columns: [], refreshing: false, meta: [] };
      const rows = Array.isArray(d) ? d : [];
      return { status: 'ok', data: rows, columns: rows.length ? Object.keys(rows[0]) : [], refreshing: false, meta: [] };
    },
    onData(fn) { cbs.push(fn); try { fn(); } catch (e) { console.error(e); } },
    calc(id, spec) { calcs.push({ id, inputs: spec.inputs || [], fn: spec.fn }); },
    loader() {},
    params() { return Object.assign({}, params); },
    setParams(p) {
      const before = JSON.stringify(params);
      params = Object.assign({}, params, p || {});
      if (status === 'ok' && JSON.stringify(params) !== before) { computeCalcs(); fire(); }
    },
    resetParams() { params = {}; if (status === 'ok') { computeCalcs(); fire(); } },
    setLink() {},
    refresh() { load(); },
    generatedAt: () => generatedAt,
  };

  async function load() {
    const before = generatedAt;
    let ok = false;
    try {
      const res = await fetch('data/data.json?t=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const j = await res.json();
      generatedAt = j.generated_at || null;
      Object.keys(j).forEach((k) => { if (Array.isArray(j[k])) store[k] = j[k]; });
      computeCalcs();
      status = 'ok';
      ok = true;
    } catch (e) {
      console.error('data.json failed to load', e);
      if (status !== 'ok') status = 'error';
    }
    const el = document.getElementById('sj-updated');
    if (el) {
      el.textContent = generatedAt
        ? new Intl.DateTimeFormat('fa-IR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran' }).format(new Date(generatedAt))
        : 'نامشخص';
    }
    // data normally lands every 6h; past 12h the sync routine has probably failed
    const stale = document.getElementById('sj-stale');
    if (stale) {
      const age = generatedAt ? (Date.now() - new Date(generatedAt).getTime()) / 36e5 : null;
      stale.hidden = !(ok && age != null && age > 12);
      const h = document.getElementById('sj-stale-hours');
      if (h && age != null) h.textContent = new Intl.NumberFormat('fa-IR').format(Math.floor(age));
    }
    fire();
    return { ok, changed: ok && generatedAt !== before };
  }

  // the button gives feedback: data only changes every ~6h, so a silent refetch looks broken
  async function refreshClick(e) {
    const b = e.currentTarget;
    if (b.disabled) return;
    const label = b.textContent;
    b.disabled = true;
    b.textContent = 'در حال دریافت…';
    const r = await load();
    b.textContent = !r.ok ? 'خطا در دریافت' : r.changed ? 'دادهٔ تازه آمد ✓' : 'به‌روز است ✓';
    setTimeout(() => { b.textContent = label; b.disabled = false; }, 2500);
  }

  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(fire, 150); });
  document.addEventListener('DOMContentLoaded', () => {
    load();
    setInterval(load, 10 * 60 * 1000); // pick up new data every 10 minutes while open
    const b = document.getElementById('sj-refresh');
    if (b) b.addEventListener('click', refreshClick);
  });
})();
