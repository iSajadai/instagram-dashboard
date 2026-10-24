/* Settings → اتصال‌ها: every data source as a card (what it gives in green, what it doesn't in grey, its
   state, a test button, a Persian step-by-step guide), the file and screenshot sources, and the coverage
   matrix. Called by settings.html: window.sjSources(). */
(function () {
  const $ = (id) => document.getElementById(id);
  const box = $('sources');
  if (!box) return;
  const FA = (t) => String(t ?? '').replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const when = (t) => { if (!t) return ''; try { return new Intl.DateTimeFormat('fa-IR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran' }).format(new Date(typeof t === 'number' ? t * 1000 : t)); } catch (e) { return ''; } };
  const KIND = { official: 'رسمی Meta', analytics: 'ابزار آنالیتیکس', scraper: 'سرویس دادهٔ عمومی', manual: 'ورود دستی' };
  const ICON = { official: 'i-shield', analytics: 'i-chart', scraper: 'i-globe', manual: 'i-pen' };
  let data = null, labels = {};

  function chips(p) {
    const all = Object.keys(labels);
    const yes = p.caps.map((c) => pn.el('span', { class: 'src-chip on' }, labels[c] || c));
    const no = all.filter((c) => !p.caps.includes(c)).map((c) => pn.el('span', { class: 'src-chip off' }, labels[c]));
    return pn.el('details', { class: 'src-caps' }, pn.el('summary', {}, 'می‌ده: ' + FA(p.caps.length) + ' مورد از ' + FA(all.length)), pn.el('div', { class: 'src-chips' }, ...yes, ...no));
  }

  function guide(p) {
    if (!p.guide || !p.guide.length) return '';
    return pn.el('details', { class: 'src-guide' }, pn.el('summary', {}, 'راهنمای قدم‌به‌قدم'),
      pn.el('ol', {}, ...p.guide.map((g) => pn.el('li', {}, g))),
      p.docs ? pn.el('a', { href: p.docs, target: '_blank', rel: 'noopener' }, 'مستند رسمی ↗') : '');
  }

  function stateLine(p) {
    const s = p.state || {};
    const out = pn.el('div', { class: 'src-state' });
    if (p.status === 'soon' || p.status === 'off') { out.append(pn.el('span', { class: 'src-badge soon' }, p.status === 'off' ? 'خاموش' : 'به‌زودی'), ' ', p.soon_reason || ''); return out; }
    if (!p.connected) { out.append(pn.el('span', { class: 'src-badge' }, 'وصل نیست')); return out; }
    out.append(pn.el('span', { class: 'src-badge ' + (s.ok === false ? 'bad' : 'ok') }, s.ok === false ? 'خطا' : 'وصله'));
    if (s.account) out.append(' ', pn.el('b', { dir: 'ltr' }, s.account));
    if (s.last_at) out.append(' · آخرین همگام‌سازی: ' + when(s.last_at));
    if (s.ok === false && s.message) out.append(pn.el('p', { class: 'pn-msg bad' }, s.message.slice(-300)));
    if (s.missing && s.missing.length) {
      out.append(pn.el('div', { class: 'src-missing' }, pn.el('b', {}, 'دسترسی‌های کم:'),
        pn.el('ul', {}, ...s.missing.map((m) => pn.el('li', {}, m.why_fa + ' — ', pn.el('code', {}, m.name))))));
    }
    return out;
  }

  function form(p) {
    const msg = pn.el('span', { class: 'pn-msg', role: 'status' });
    if (p.status !== 'ready') return '';
    if (p.id === 'export_csv' || p.id === 'dyi_json') {
      const inp = pn.el('input', { type: 'file', accept: p.upload });
      const btn = pn.el('button', { type: 'button', class: 'primary' }, 'آپلود و خوندن');
      btn.addEventListener('click', () => pn.run(btn, msg, async () => {
        const f = inp.files[0]; if (!f) throw new Error('اول فایل رو انتخاب کن');
        const r = await fetch('/api/me/providers/' + p.id + '/upload?name=' + encodeURIComponent(f.name), { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'sajadai' }, body: f });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || 'آپلود نشد');
        load(); return d;
      }));
      return pn.el('div', { class: 'pn-row' }, inp, btn, msg);
    }
    if (p.id === 'screenshot') return screenshotForm(msg);
    if (p.id === 'manual') return manualForm({}, 'manual', msg);
    const inputs = Object.entries(p.fields).map(([f, label]) => {
      const secret = p.secret_fields.includes(f);
      const i = pn.el('input', { 'data-f': f, dir: 'ltr', autocomplete: 'off', type: secret ? 'password' : 'text', value: (p.values || {})[f] || (f === 'branch' ? 'main' : '') });
      return pn.el('label', {}, label, i);
    });
    const save = pn.el('button', { type: 'button', class: 'primary' }, p.connected ? 'ذخیره و تست' : 'وصل کن');
    const vals = () => Object.fromEntries([...save.closest('.src-card').querySelectorAll('[data-f]')].map((i) => [i.dataset.f, i.value.trim()]));
    save.addEventListener('click', () => pn.run(save, msg, async () => { const r = await pn.api('POST', '/api/me/providers/' + p.id, vals()); await load(); return { ok: r.ok, message: r.message_fa }; }));
    const row = [save];
    if (p.connected) {
      const t = pn.el('button', { type: 'button' }, 'تست اتصال');
      t.addEventListener('click', () => pn.run(t, msg, async () => { const r = await pn.api('POST', '/api/me/providers/' + p.id + '/test'); await load(); return { ok: r.ok, message: r.message_fa }; }));
      const del = pn.el('button', { type: 'button', class: 'danger' }, 'قطع');
      del.addEventListener('click', () => { if (confirm('اتصال ' + p.title + ' قطع بشه؟ عددهای قبلی تو تاریخچه می‌مونن.')) pn.run(del, msg, async () => { await pn.api('DELETE', '/api/me/providers/' + p.id); await load(); return { ok: true, message: 'قطع شد' }; }); });
      row.push(t, del);
    }
    const extra = [];
    if (p.callback) extra.push(pn.el('p', { class: 'pn-note' }, 'Callback URL: ', pn.el('code', { dir: 'ltr' }, p.callback), ' · Verify token: ', pn.el('code', { dir: 'ltr' }, p.verify_token)));
    if (p.deploy_key) extra.push(pn.el('details', {}, pn.el('summary', {}, 'کلید فقط‌خواندنی پنل (Deploy key)'), pn.el('pre', { dir: 'ltr', class: 'src-key' }, p.deploy_key)));
    return pn.el('div', { class: 'src-form' }, pn.el('div', { class: 'pn-grid' }, ...inputs), ...extra, pn.el('div', { class: 'pn-row' }, ...row, msg));
  }

  const NUMS = [['views', 'بازدید'], ['reach', 'دسترسی'], ['likes', 'لایک'], ['comments', 'کامنت'], ['saves', 'ذخیره'], ['shares', 'اشتراک'],
    ['follows', 'فالوئر از ریل'], ['avg_watch', 'میانگین تماشا (ثانیه)'], ['watch_total', 'کل تماشا (ثانیه)'], ['duration', 'مدت ویدیو (ثانیه)'], ['view_rate', 'ماندن ۳ ثانیه (٪)']];
  function manualForm(values, source, msg) {
    const url = pn.el('input', { dir: 'ltr', placeholder: 'https://www.instagram.com/reel/…', 'data-m': 'url', value: values.url || '' });
    const nums = NUMS.map(([k, l]) => pn.el('label', {}, l, pn.el('input', { 'data-m': k, inputmode: 'decimal', dir: 'ltr', value: values[k] == null ? '' : values[k] })));
    const save = pn.el('button', { type: 'button', class: 'primary' }, source === 'screenshot' ? 'تأیید و ذخیره' : 'ذخیره');
    const wrap = pn.el('div', { class: 'src-form' }, pn.el('label', {}, 'لینک ریل', url), pn.el('div', { class: 'pn-grid src-nums' }, ...nums), pn.el('div', { class: 'pn-row' }, save, msg));
    save.addEventListener('click', () => pn.run(save, msg, async () => {
      const b = { source };
      wrap.querySelectorAll('[data-m]').forEach((i) => { b[i.dataset.m] = i.value.trim(); });
      const r = await pn.api('POST', '/api/me/providers/manual/save', b); await load(); return r;
    }));
    return wrap;
  }
  function screenshotForm(msg) {
    const url = pn.el('input', { dir: 'ltr', placeholder: 'لینک ریل: https://www.instagram.com/reel/…' });
    const inp = pn.el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', multiple: '' });
    const read = pn.el('button', { type: 'button', class: 'primary' }, 'خوندن عددها');
    const out = pn.el('div');
    read.addEventListener('click', () => pn.run(read, msg, async () => {
      const fs = [...inp.files].slice(0, 4); if (!fs.length) throw new Error('اسکرین‌شات رو انتخاب کن');
      const images = await Promise.all(fs.map((f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); })));
      const r = await pn.api('POST', '/api/me/providers/screenshot/read', { images });
      out.replaceChildren(pn.el('p', { class: 'pn-note' }, 'عددهای پیشنهادی رو چک کن و اگه لازمه درستشون کن، بعد ذخیره کن.' + (r.numbers.notes ? ' ' + r.numbers.notes : '')),
        manualForm({ ...r.numbers, url: url.value.trim() }, 'screenshot', pn.el('span', { class: 'pn-msg' })));
      return { ok: true, message: 'خونده شد؛ پایین چک کن' };
    }));
    return pn.el('div', { class: 'src-form' }, url, pn.el('div', { class: 'pn-row' }, inp, read, msg), out);
  }

  function icon(id) {  // SVG has to be made in its own namespace
    const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), u = document.createElementNS(NS, 'use');
    u.setAttribute('href', '#' + id); s.append(u); return s;
  }
  function card(p) {
    const head = pn.el('div', { class: 'src-head' },
      pn.el('span', { class: 'src-ico', 'aria-hidden': 'true' }, icon(ICON[p.kind])),
      pn.el('div', {}, pn.el('b', {}, p.title), pn.el('div', { class: 'src-tags' }, pn.el('span', { class: 'src-tier ' + p.tier }, p.tier_fa), pn.el('span', { class: 'src-kind' }, KIND[p.kind]))));
    const c = pn.el('article', { class: 'src-card' + (p.connected ? ' is-on' : '') + (p.status !== 'ready' ? ' is-soon' : ''), id: 'src-' + p.id },
      head, pn.el('p', { class: 'pn-note' }, p.description), stateLine(p), chips(p), form(p), guide(p));
    if (p.kind === 'scraper') c.append(pn.el('p', { class: 'src-warn' }, '⚠️ این سرویس‌ها داده رو از صفحه‌های عمومی جمع می‌کنن و ممکنه با قوانین اینستاگرام در تضاد باشن؛ مسئولیت استفاده با خودته.'));
    return c;
  }

  function coverage(cov) {
    const box2 = $('coverage');
    if (!box2) return;
    const where = (i) => {
      if (i.state === 'ok') return '✓ ' + (i.sources.map(titleOf).join('، ') || 'داده رسیده');
      if (i.state === 'waiting') return '⏳ منتظر داده از ' + i.sources.map(titleOf).join('، ');
      return '—';
    };
    const fix = (i) => {
      if (i.state !== 'missing' || !i.suggest.length) return '';
      const links = i.suggest.flatMap((s, k) => [k ? '، ' : '', pn.el('a', { href: '#src-' + s.id }, s.title)]);
      return pn.el('span', {}, 'وصل کن: ', ...links);
    };
    box2.replaceChildren(...cov.groups.map((g) => {
      const rows = g.items.map((i) => pn.el('tr', { class: 'cov-' + i.state }, pn.el('td', {}, i.label), pn.el('td', {}, where(i)), pn.el('td', {}, fix(i))));
      return pn.el('div', { class: 'cov-group' }, pn.el('h3', {}, g.title), pn.el('table', { class: 'cov-table' }, pn.el('tbody', {}, ...rows)));
    }));
  }
  const titleOf = (id) => ((data.providers.find((p) => p.id === id) || {}).title || id);

  async function load() {
    try { data = await pn.api('GET', '/api/me/providers'); } catch (e) { return; }
    labels = Object.fromEntries(data.coverage.groups.flatMap((g) => g.items.map((i) => [i.id, i.label])));
    const groups = [['official', 'رسمی Meta (رایگان، با حساب Business یا Creator)'], ['analytics', 'ابزارهای آنالیتیکس و زمان‌بندی'],
      ['scraper', 'سرویس‌های دادهٔ عمومی (پولی)'], ['manual', 'ورود دستی (رایگان)']];
    box.replaceChildren(...groups.map(([k, title]) => {
      const ps = data.providers.filter((p) => p.kind === k);
      return ps.length ? pn.el('section', { class: 'src-group' }, pn.el('h3', {}, title), pn.el('div', { class: 'src-grid' }, ...ps.map(card))) : '';
    }));
    coverage(data.coverage);
    const dis = $('discrepancies');
    if (dis) dis.textContent = data.discrepancies.length ? 'اختلاف بیش از ۱۰٪ بین منبع‌ها (آخرین‌ها): ' + data.discrepancies.slice(-5).map((x) => x.reel + ' / ' + x.field).join('، ') : '';
    if (location.hash.startsWith('#src-')) { const el = document.querySelector(location.hash); if (el) el.scrollIntoView(); }
  }
  window.sjSources = load;
  load();
})();
