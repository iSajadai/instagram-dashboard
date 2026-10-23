/* Settings → لینک بایو: the links, their order, and each one's clicks over 7 and 30 days. */
(function () {
  const $ = (id) => document.getElementById(id);
  if (!$('bio-card')) return;
  const FA = (t) => String(t).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  let data = null;

  function row(l, i, n) {
    const st = (data.stats.links || {})[l.id] || {};
    const title = pn.el('input', { 'data-k': 'title', value: l.title || '', maxlength: '80', placeholder: 'عنوان، مثلاً: دورهٔ رایگان', 'aria-label': 'عنوان لینک ' + (i + 1) });
    const url = pn.el('input', { 'data-k': 'url', value: l.url || '', dir: 'ltr', inputmode: 'url', placeholder: 'https://…', 'aria-label': 'آدرس لینک ' + (i + 1) });
    const hi = pn.el('input', { type: 'checkbox', 'data-k': 'highlight' }); hi.checked = !!l.highlight;
    const move = (d) => { const ls = read(); const [x] = ls.splice(i, 1); ls.splice(i + d, 0, x); data.links = ls; draw(); };
    return pn.el('div', { class: 'bio-link', 'data-id': l.id || '' },
      pn.el('div', { class: 'pn-grid' }, title, url),
      pn.el('div', { class: 'pn-row' },
        pn.el('label', { class: 'pn-check' }, hi, 'برجسته'),
        pn.el('span', { class: 'pn-note' }, l.id ? `کلیک: ${FA(st.clicks_7 || 0)} در ۷ روز · ${FA(st.clicks_30 || 0)} در ۳۰ روز` : 'تازه'),
        pn.el('button', { type: 'button', 'aria-label': 'بالاتر', disabled: i === 0 ? '' : null, onclick: () => move(-1) }, '↑'),
        pn.el('button', { type: 'button', 'aria-label': 'پایین‌تر', disabled: i === n - 1 ? '' : null, onclick: () => move(1) }, '↓'),
        pn.el('button', { type: 'button', onclick: () => { const ls = read(); ls.splice(i, 1); data.links = ls; draw(); } }, 'حذف')));
  }
  const read = () => [...$('bio-links').querySelectorAll('.bio-link')].map((el) => {
    const o = { id: el.dataset.id };
    el.querySelectorAll('[data-k]').forEach((x) => { o[x.dataset.k] = x.type === 'checkbox' ? x.checked : x.value; });
    return o;
  });
  function draw() {
    $('bio-links').replaceChildren(...data.links.map((l, i) => row(l, i, data.links.length)));
    $('bio-add').disabled = data.links.length >= 12;
    $('bio-link-row').hidden = !data.url;
    if (data.url) { $('bio-url').textContent = data.url; $('bio-open').href = data.url; }
    const s = data.stats, clicks7 = Object.values(s.links || {}).reduce((a, x) => a + (x.clicks_7 || 0), 0);
    $('bio-stats').textContent = data.enabled
      ? `بازدید صفحه: ${FA(s.views_7)} در ۷ روز، ${FA(s.views_30)} در ۳۰ روز · کلیک ۷ روز: ${FA(clicks7)}${s.views_7 ? ' · نرخ کلیک ' + FA(Math.round(clicks7 / s.views_7 * 100)) + '٪' : ''}`
      : '';
  }
  async function load() {
    try { data = await pn.api('GET', '/api/me/bio'); } catch (e) { return; }
    $('bio_enabled').checked = !!data.enabled;
    $('bio_slug').value = data.slug || data.suggest.slug || '';
    $('bio_handle').value = data.handle || data.suggest.handle || '';
    $('bio_title').value = data.title || data.suggest.title || '';
    $('bio_text').value = data.text || '';
    $('bio_utm').checked = data.utm !== false;
    if (!data.links.length) data.links = [{ title: '', url: '' }];
    draw();
  }
  $('bio-add').addEventListener('click', () => { data.links = [...read(), { title: '', url: '' }]; draw(); $('bio-links').lastElementChild.querySelector('input').focus(); });
  $('save-bio').addEventListener('click', (e) => pn.run(e.currentTarget, $('bio-msg'), async () => {
    const r = await pn.api('POST', '/api/me/bio', { enabled: $('bio_enabled').checked, slug: $('bio_slug').value.trim(), handle: $('bio_handle').value.trim(),
      title: $('bio_title').value.trim(), text: $('bio_text').value.trim(), utm: $('bio_utm').checked, links: read() });
    await load();
    return { ok: true, message: r.url ? 'ذخیره شد ✓ این لینک رو تو بایو اینستاگرام بذار.' : 'ذخیره شد' };
  }));
  load();
})();
