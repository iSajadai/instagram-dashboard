/* Screenshot analysis (#/screenshot): the no-setup way to get data in — upload screenshots of the
   Instagram Insights screens, a vision model reads the numbers, writes a Persian analysis and fills
   the dashboard. Uploads each image to /api/me/ig/upload?kind=shot, then posts the names to
   /api/me/screenshot. Needs the panel. */
(function () {
  const go = document.getElementById('shot-go');
  if (!go) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fa = (n) => (n == null ? '' : Number(n).toLocaleString('fa-IR'));
  const fileInput = $('shot-file'), list = $('shot-list'), clearBtn = $('shot-clear'), result = $('shot-result');
  const msg = (t, bad) => { const m = $('shot-msg'); if (m) { m.textContent = t || ''; m.style.color = bad ? 'var(--coral)' : ''; } };
  let files = [];

  function redraw() {
    list.replaceChildren(...files.map((f, i) => {
      const chip = document.createElement('span');
      chip.className = 'sj-chip';
      chip.innerHTML = esc(f.name.length > 24 ? f.name.slice(0, 22) + '…' : f.name) + ' ✕';
      chip.style.cursor = 'pointer';
      chip.title = 'برداشتن';
      chip.onclick = () => { files.splice(i, 1); redraw(); };
      return chip;
    }));
    go.disabled = !files.length;
    clearBtn.hidden = !files.length;
    if (files.length) msg(files.length + ' عکس انتخاب شد');
  }

  fileInput.addEventListener('change', () => {
    for (const f of fileInput.files) {
      if (files.length >= 8) { msg('حداکثر ۸ عکس', true); break; }
      if (f.type.startsWith('image/')) files.push(f);
    }
    fileInput.value = '';
    redraw();
  });
  clearBtn.addEventListener('click', () => { files = []; redraw(); msg(''); result.replaceChildren(); });

  async function upload(file) {
    const r = await fetch('/api/me/ig/upload?kind=shot', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-Requested-With': 'sajadai', 'Content-Type': 'application/octet-stream' }, body: file,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'آپلود نشد');
    return d.name;
  }

  async function analyze(names) {
    const r = await fetch('/api/me/screenshot', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-Requested-With': 'sajadai', 'Content-Type': 'application/json' }, body: JSON.stringify({ images: names }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'خطا (' + r.status + ')');
    return d;
  }

  function render(d) {
    const f = d.filled || {};
    const bits = [];
    if (f.followers != null) bits.push(fa(f.followers) + ' دنبال‌کننده');
    if (f.reels) bits.push(fa(f.reels) + ' ریل');
    const parts = [];
    if (bits.length) parts.push(`<div class="sj-chip ok" style="margin-bottom:12px">داشبورد به‌روز شد: ${esc(bits.join(' · '))}</div>`);
    else parts.push(`<div class="sj-chip" style="margin-bottom:12px">عددی برای پر کردنِ داشبورد خونده نشد؛ تحلیل زیر رو ببین.</div>`);
    if (d.analysis) parts.push(`<div class="sj-card" style="padding:16px;margin-bottom:12px"><h3 class="sj-h3">تحلیل</h3><p style="white-space:pre-wrap;line-height:1.9">${esc(d.analysis)}</p></div>`);
    if (Array.isArray(d.suggestions) && d.suggestions.length) {
      parts.push(`<div class="sj-card" style="padding:16px;margin-bottom:12px"><h3 class="sj-h3">پیشنهادها</h3><ul style="line-height:2;padding-inline-start:1.2em">${d.suggestions.map((s) => `<li>${esc(s)}</li>`).join('')}</ul></div>`);
    }
    if (d.read_notes) parts.push(`<p class="sj-small" style="opacity:.8">یادداشت: ${esc(d.read_notes)}</p>`);
    if (bits.length) parts.push(`<a class="sj-btn sj-btn-primary" href="#/top" style="margin-top:4px">دیدن داشبورد</a>`);
    result.innerHTML = parts.join('');
  }

  go.addEventListener('click', async () => {
    if (!files.length) return;
    go.disabled = true; clearBtn.disabled = true; result.replaceChildren();
    try {
      const names = [];
      for (let i = 0; i < files.length; i++) { msg(`آپلود عکس ${i + 1} از ${files.length}…`); names.push(await upload(files[i])); }
      msg('در حال خوندن و تحلیل… (چند لحظه)');
      const d = await analyze(names);
      render(d);
      msg('انجام شد ✓'); setTimeout(() => msg(''), 2500);
      files = []; redraw();
    } catch (e) { msg(e.message, true); }
    finally { go.disabled = false; clearBtn.disabled = false; }
  });
})();
