/* Publish a reel (#/publish): upload the video (streamed to the panel, which serves it to Instagram at
   an unguessable address), make a 1080×1920 cover from a frame or a photo with a Persian title, check
   the caption, and publish now or at a Tehran time. The queue below shows each post as the scheduler
   moves it along (scheduled → processing → published). Needs the panel, like tools.js. */
(function () {
  const sec = document.getElementById('publish');
  if (!sec) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const FA = (t) => String(t).replace(/(\d)\.(\d)/g, '$1٫$2').replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const jWhen = new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tehran' });
  async function api(method, path, body) {
    const r = await fetch(path, {
      method, credentials: 'same-origin',
      headers: { 'X-Requested-With': 'sajadai', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'خطا (' + r.status + ')');
    return data;
  }
  const say = (el, text, bad) => { el.textContent = text || ''; el.style.color = bad ? 'var(--coral)' : ''; };

  // ---------- 1. the video ----------
  const MAX = 100 * 1024 * 1024;
  let video = null, cover = null, uploading = false;
  const vid = $('pub-preview');

  function upload(file, kind, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', '/api/me/ig/upload?kind=' + kind);
      x.setRequestHeader('X-Requested-With', 'sajadai');
      x.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
      x.onload = () => {
        let d = {};
        try { d = JSON.parse(x.responseText); } catch (e) { /* not json */ }
        if (x.status === 200) resolve(d);
        else reject(new Error(typeof d.detail === 'string' ? d.detail : x.status === 413 ? 'فایل بزرگ‌تر از ۱۰۰ مگابایته' : 'آپلود نشد (' + x.status + ')'));
      };
      x.onerror = () => reject(new Error('اینترنت قطع شد؛ دوباره امتحان کن'));
      x.send(file);
    });
  }

  async function pickVideo(file) {
    if (!file) return;
    const info = $('pub-vinfo');
    if (!/^video\/(mp4|quicktime)$/.test(file.type) && !/\.(mp4|mov)$/i.test(file.name)) { say(info, 'فقط MP4 یا MOV', true); return; }
    if (file.size > MAX) { say(info, 'فایل ' + FA(Math.round(file.size / 1048576)) + ' مگابایته؛ حداکثر ۱۰۰. با CapCut یا HandBrake کم‌حجمش کن.', true); return; }
    video = null;
    vid.src = URL.createObjectURL(file);
    vid.hidden = false;
    await new Promise((r) => { vid.onloadedmetadata = r; vid.onerror = r; });
    const d = vid.duration || 0, w = vid.videoWidth, h = vid.videoHeight;
    const notes = [];
    if (d && (d < 3 || d > 900)) { say(info, 'ریل باید بین ۳ ثانیه تا ۱۵ دقیقه باشه؛ این ' + FA(Math.round(d)) + ' ثانیه است.', true); return; }
    if (w && h && Math.abs(w / h - 9 / 16) > 0.02) notes.push('نسبتش ' + FA(w) + '×' + FA(h) + ' است، نه ۹:۱۶؛ اینستاگرام لبه‌ها رو می‌بره یا نوار مشکی می‌ذاره.');
    $('cover-time').disabled = false;
    drawCover();
    const bar = $('pub-progress');
    bar.hidden = false; uploading = true; syncGo();
    say(info, 'در حال آپلود…');
    try {
      const r = await upload(file, 'video', (p) => { bar.firstElementChild.style.width = Math.round(p * 100) + '%'; say(info, 'در حال آپلود… ' + FA(Math.round(p * 100)) + '٪'); });
      video = r.name;
      say(info, ['آپلود شد ✓ · ' + FA(Math.round(d)) + ' ثانیه · ' + FA((file.size / 1048576).toFixed(1)) + ' مگابایت', ...notes].join(' · '));
      $('pub-critique').hidden = false; $('pub-transcript-box').hidden = false;
    } catch (e) { say(info, e.message, true); }
    finally { bar.hidden = true; uploading = false; syncGo(); }
  }
  $('pub-file').addEventListener('change', (e) => pickVideo(e.target.files[0]));
  const drop = $('pub-drop');
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, () => drop.classList.remove('over')));
  drop.addEventListener('drop', (e) => { e.preventDefault(); pickVideo(e.dataTransfer.files[0]); });
  // ---------- critique before publishing ----------
  const at = (s) => FA(Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0'));
  $('pub-critique').addEventListener('click', async (e) => {
    const b = e.currentTarget, out = $('pub-critique-out');
    if (!video) return;
    b.disabled = true;
    out.innerHTML = '<p class="sj-small" role="status">شروع شد…</p>';
    try {
      const { job } = await api('POST', '/api/me/ig/critique', { video, transcript: $('pub-transcript').value });
      let s;
      for (;;) {
        await new Promise((r) => setTimeout(r, 2500));
        s = await api('GET', '/api/me/ig/critique/' + job);
        if (s.status !== 'running') break;
        out.innerHTML = `<p class="sj-small" role="status">${esc(s.step)}</p>`;
      }
      if (s.status === 'failed') throw new Error(s.error);
      drawCritique(s.result);
    } catch (err) { out.innerHTML = `<p class="sj-error">${esc(err.message)}</p>`; }
    b.disabled = false;
  });
  function drawCritique(r) {
    const out = $('pub-critique-out'), h = r.hook_score;
    const cls = h.verdict === 'STRONG' ? 'sj-ok' : h.verdict === 'WEAK' ? 'sj-late' : '';
    out.innerHTML = `
      <div class="sj-crit"><h4>${esc(r.verdict)}</h4><p class="sj-small">${esc(r.summary_fa)}${r.source === 'paste' ? ' · زمان‌بندی تخمینی' : ''}</p></div>
      <div class="sj-crit"><h4>۳ ثانیهٔ اول <span class="sj-chip ${cls}">${FA(h.overall)} از ۱۰۰ · ${esc(h.verdict_fa)}</span></h4>
        <p>«${esc(r.hook_text)}»</p>${h.weakest_fa ? `<p class="sj-small">ضعیف‌ترین بخش: ${esc(h.weakest_fa)}</p>` : ''}<p>${esc(r.hook)}</p></div>
      <div class="sj-crit"><h4>فریم اول</h4><p>${esc(r.first_frame)}</p></div>
      <div class="sj-crit"><h4>ریتم</h4><p>${esc(r.pacing)}</p>
        <p class="sj-small">${r.pace.first_word != null ? 'اولین کلمه: ثانیهٔ ' + FA(r.pace.first_word) : ''}${r.pace.gaps.length ? ' · سکوت‌ها: ' + r.pace.gaps.map((g) => at(g.at) + ' (' + FA(g.secs) + ' ثانیه)').join('، ') : ''}</p></div>
      <div class="sj-crit"><h4>تصویر</h4><p>${esc(r.visuals)}</p></div>
      ${r.fixes.length ? `<div class="sj-crit"><h4>اصلاح‌ها به ترتیب اثر</h4><ol>${r.fixes.map((f) => `<li>${esc(f)}</li>`).join('')}</ol></div>` : ''}
      ${r.better_hooks.length ? `<div class="sj-crit"><h4>هوک‌های جایگزین</h4>${r.better_hooks.map((x) => `<p>«${esc(x.text)}» <span class="sj-chip">${FA(x.overall)}</span></p>`).join('')}</div>` : ''}
      <div class="sj-row-btns"><button type="button" class="sj-btn" id="pub-srt">دانلود زیرنویس SRT</button><button type="button" class="sj-btn" id="pub-srt-cap">متن ریل → کپشن</button></div>`;
    $('pub-srt').addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(['﻿' + r.srt], { type: 'application/x-subrip' }));
      a.download = 'reel-fa.srt'; a.click();
    });
    $('pub-srt-cap').addEventListener('click', () => {
      const c = $('pub-caption');
      if (!c.value.trim() || confirm('کپشن فعلی با متن ریل عوض بشه؟')) { c.value = r.segments.map((s) => s.text).join('\n'); c.dispatchEvent(new Event('input')); }
    });
  }

  // ---------- 2. the cover ----------
  const cv = $('cover-canvas'), ctx = cv.getContext('2d');
  let bg = null;  // an uploaded photo
  const fontReady = document.fonts ? document.fonts.load('900 96px "Vazirmatn Variable"').catch(() => {}) : Promise.resolve();

  function wrap(text, maxW) {
    const lines = [];
    String(text).split('\n').forEach((para) => {
      let line = '';
      para.split(/\s+/).filter(Boolean).forEach((w) => {
        const t = line ? line + ' ' + w : w;
        if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = w; } else line = t;
      });
      if (line) lines.push(line);
    });
    return lines.slice(0, 5);
  }
  function cover_fit(src, sw, sh) {  // fill 1080×1920, cropping the overflow from the middle
    const s = Math.max(1080 / sw, 1920 / sh), w = sw * s, h = sh * s;
    ctx.drawImage(src, (1080 - w) / 2, (1920 - h) / 2, w, h);
  }
  async function drawCover() {
    await fontReady;
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, 1080, 1920);
    if (bg) cover_fit(bg, bg.naturalWidth, bg.naturalHeight);
    else if (vid.videoWidth) cover_fit(vid, vid.videoWidth, vid.videoHeight);
    const text = $('cover-text').value.trim();
    if (!text) return;
    const size = Number($('cover-size').value), style = $('cover-style').value, pos = $('cover-pos').value;
    ctx.font = `900 ${size}px "Vazirmatn Variable", Vazirmatn, Tahoma, sans-serif`;
    ctx.direction = 'rtl'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    const lines = wrap(text.replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]), 900);
    const lh = size * 1.35, block = lh * lines.length;
    // centre stays inside the 3:4 crop the profile grid shows; top and bottom keep clear of Instagram's buttons
    const cy = pos === 'top' ? 330 + block / 2 : pos === 'bottom' ? 1460 - block / 2 : 960;
    lines.forEach((l, i) => {
      const y = cy - block / 2 + lh * (i + 0.5);
      if (style === 'box') {
        const w = ctx.measureText(l).width + size * 0.8;
        ctx.fillStyle = '#fff'; ctx.beginPath();
        (ctx.roundRect ? ctx.roundRect(540 - w / 2, y - lh / 2 + 4, w, lh - 8, 18) : ctx.rect(540 - w / 2, y - lh / 2 + 4, w, lh - 8));
        ctx.fill(); ctx.fillStyle = '#111'; ctx.shadowBlur = 0;
      } else {
        ctx.fillStyle = style === 'yellow' ? '#ffd60a' : '#fff';
        ctx.shadowColor = 'rgba(0,0,0,.75)'; ctx.shadowBlur = 24; ctx.shadowOffsetY = 4;
      }
      ctx.fillText(l, 540, y);
      ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
    });
  }
  const seek = () => { if (vid.duration) { bg = null; vid.currentTime = vid.duration * Number($('cover-time').value) / 1000; } };
  $('cover-time').addEventListener('input', seek);
  vid.addEventListener('seeked', drawCover);
  ['cover-text', 'cover-size', 'cover-style', 'cover-pos'].forEach((id) => $(id).addEventListener('input', drawCover));
  $('cover-img').addEventListener('change', (e) => {
    const f = e.target.files[0]; if (!f) return;
    const img = new Image();
    img.onload = () => { bg = img; drawCover(); };
    img.src = URL.createObjectURL(f);
  });
  $('cover-guide').addEventListener('change', (e) => $('cover-wrap').classList.toggle('no-guide', !e.target.checked));
  const coverBlob = () => new Promise((r) => cv.toBlob(r, 'image/jpeg', 0.9));
  $('cover-download').addEventListener('click', async () => {
    await drawCover();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await coverBlob()); a.download = 'cover-1080x1920.jpg'; a.click();
  });
  $('cover-use').addEventListener('click', async (e) => {
    const b = e.currentTarget; b.disabled = true;
    try {
      await drawCover();
      cover = (await upload(await coverBlob(), 'cover')).name;
      say($('cover-msg'), 'کاور آماده‌ست ✓ با ریل فرستاده می‌شه.');
    } catch (err) { say($('cover-msg'), err.message, true); }
    b.disabled = false;
  });
  drawCover();

  // ---------- 3. caption, time, publish ----------
  let lintTimer = null;
  $('pub-caption').addEventListener('input', () => {
    clearTimeout(lintTimer);
    lintTimer = setTimeout(async () => {
      const text = $('pub-caption').value.trim();
      const out = $('pub-caption-lint');
      if (!text) { out.textContent = ''; return; }
      try {
        const r = await api('POST', '/api/me/fa/caption', { text });
        const bad = (r.checks || []).filter((c) => c.status !== 'PASS').slice(0, 3).map((c) => c.check + ': ' + c.detail);
        out.innerHTML = `<b>${esc(r.verdict_fa || '')}</b>${bad.length ? ' · ' + bad.map(esc).join(' · ') : ''} · ${FA(text.length)} از ۲٬۲۰۰ حرف`;
      } catch (e) { out.textContent = FA(text.length) + ' از ۲٬۲۰۰ حرف'; }
    }, 700);
  });
  $('pub-when-mode').addEventListener('change', (e) => { $('pub-when').hidden = e.target.value !== 'at'; syncGo(); });
  function syncGo() {
    const go = $('pub-go');
    go.disabled = !video || uploading;
    go.textContent = $('pub-when-mode').value === 'at' ? 'زمان‌بندی' : 'انتشار';
  }
  // the hours to suggest: when followers are online (Instagram), else the page's own best-time data
  async function bestHours() {
    const box = $('pub-best');
    try {
      const r = await api('GET', '/api/me/ig/online');
      if (!r.hours || !r.hours.length) return;
      const top = [...r.hours].sort((a, b) => b.online - a.online).slice(0, 3).map((h) => h.hour);
      box.innerHTML = '<span class="sj-small">فالوئرهات بیشتر این ساعت‌ها آنلاین‌اند:</span> ' +
        top.map((h) => `<button type="button" class="sj-chip-btn" data-hour="${h}">${FA(String(Math.floor(h)).padStart(2, '0') + ':' + (h % 1 ? '30' : '00'))}</button>`).join(' ');
    } catch (e) { /* no suggestion */ }
  }
  $('pub-best').addEventListener('click', (e) => {
    const b = e.target.closest('[data-hour]'); if (!b) return;
    const h = Number(b.dataset.hour);
    const now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Tehran' }));
    const t = new Date(now); t.setHours(Math.floor(h), h % 1 ? 30 : 0, 0, 0);
    if (t <= now) t.setDate(t.getDate() + 1);
    const p = (n) => String(n).padStart(2, '0');
    $('pub-when-mode').value = 'at'; $('pub-when').hidden = false;
    $('pub-when').value = `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}T${p(t.getHours())}:${p(t.getMinutes())}`;
    syncGo();
  });
  $('pub-go').addEventListener('click', async (e) => {
    const b = e.currentTarget, msg = $('pub-msg');
    const at = $('pub-when-mode').value === 'at';
    if (at && !$('pub-when').value) { say(msg, 'تاریخ و ساعت رو انتخاب کن', true); return; }
    if (!cover && $('cover-text').value.trim() && !confirm('متن کاور رو نوشتی ولی «استفاده به‌عنوان کاور» رو نزدی. بدون کاور منتشر بشه؟')) return;
    b.disabled = true;
    try {
      await api('POST', '/api/me/ig/queue', { video, cover, caption: $('pub-caption').value, when: at ? $('pub-when').value : null,
        share_to_feed: $('pub-feed').checked, thumb_offset: cover ? 0 : Math.round((vid.currentTime || 0) * 1000), card: sec.dataset.card || '' });
      say(msg, at ? 'زمان‌بندی شد ✓ سر ساعت خودکار منتشر می‌شه.' : 'تو صف انتشاره ✓ معمولاً چند دقیقه طول می‌کشه؛ وقتی منتشر شد اعلان می‌گیری.');
      video = null; cover = null; vid.hidden = true; vid.removeAttribute('src'); $('pub-file').value = ''; $('pub-vinfo').textContent = '';
      $('pub-caption').value = ''; $('pub-caption-lint').textContent = ''; $('cover-msg').textContent = ''; delete sec.dataset.card;
      loadQueue();
    } catch (err) { say(msg, err.message, true); }
    syncGo();
  });

  // ---------- the queue ----------
  const STATUS = { scheduled: ['زمان‌بندی‌شده', ''], processing: ['در حال پردازش', 'sj-chip-buffer'], published: ['منتشر شد', 'sj-ok'], failed: ['منتشر نشد', 'sj-late'] };
  let poll = null;
  async function loadQueue() {
    const box = $('pub-queue');
    let r;
    try { r = await api('GET', '/api/me/ig/queue'); } catch (e) { box.innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; return; }
    if (!r.connected) { box.innerHTML = window.vfEmpty('i-link', 'اینستاگرام وصل نیست', 'برای انتشار مستقیم، Instagram API رو با دسترسی انتشار (instagram_business_content_publish) وصل کن.', '<a class="sj-btn" href="/settings#conns-card">تنظیمات اتصال‌ها</a>'); return; }
    if (!r.public_url) { box.innerHTML = `<p class="sj-error">آدرس عمومی https پنل تنظیم نشده؛ اینستاگرام ویدیو رو باید از اونجا برداره. ادمین از «پنل مدیریت» تنظیمش کنه.</p>`; return; }
    if (!r.items.length) { box.innerHTML = '<p class="sj-note">هنوز چیزی تو صف نیست.</p>'; return; }
    box.innerHTML = r.items.map((i) => {
      const [label, cls] = STATUS[i.status] || [i.status, ''];
      return `<div class="sj-qrow">
        <div><b>${esc((i.caption || 'بدون کپشن').split('\n')[0].slice(0, 80))}</b>
          <p class="sj-small">${esc(jWhen.format(new Date((i.published || i.when) * 1000)))}${i.note ? ' · ' + esc(i.note) : ''}</p></div>
        <span class="sj-chip ${cls}">${label}</span>
        ${i.permalink ? `<a class="sj-btn" href="${esc(i.permalink)}" target="_blank" rel="noopener">دیدن</a>` : ''}
        ${i.status === 'scheduled' || i.status === 'failed' ? `<button type="button" class="sj-btn" data-cancel="${esc(i.id)}">${i.status === 'failed' ? 'پاک کردن' : 'لغو'}</button>` : ''}
      </div>`;
    }).join('');
    clearTimeout(poll);
    if (r.items.some((i) => i.status === 'processing' || (i.status === 'scheduled' && i.when * 1000 < Date.now() + 120000))) poll = setTimeout(loadQueue, 20000);
    api('GET', '/api/me/ig/limit').then((l) => { $('pub-limit').textContent = `انتشار ۲۴ ساعت اخیر: ${FA(l.used)} از ${FA(l.total)}`; }).catch(() => {});
  }
  $('pub-queue').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-cancel]'); if (!b) return;
    b.disabled = true;
    try { await api('DELETE', '/api/me/ig/queue/' + b.dataset.cancel); loadQueue(); } catch (err) { b.disabled = false; alert(err.message); }
  });

  // best-time page: followers online by hour
  async function drawOnline() {
    const box = $('online-chart'), note = $('online-note');
    if (!box) return;
    let r;
    try { r = await api('GET', '/api/me/ig/online'); } catch (e) { note.textContent = e.message; return; }
    if (!r.hours || !r.hours.length) { box.innerHTML = ''; note.textContent = r.reason || 'اینستاگرام این آمار رو نداد.'; return; }
    const max = Math.max(...r.hours.map((h) => h.online)) || 1;
    const top = [...r.hours].sort((a, b) => b.online - a.online).slice(0, 3).map((h) => h.hour);
    const label = (h) => FA(String(Math.floor(h)).padStart(2, '0') + ':' + (h % 1 ? '30' : '00'));
    box.innerHTML = r.hours.map((h) => `<div class="sj-ob${top.includes(h.hour) ? ' top' : ''}" title="${label(h.hour)}: ${FA(h.online)} نفر">
      <span style="height:${Math.max(4, Math.round(h.online / max * 100))}%"></span><small>${h.hour % 3 === 0 || h.hour % 3 === 0.5 ? label(h.hour) : ''}</small></div>`).join('');
    note.textContent = 'اوج: ' + top.sort((a, b) => a - b).map(label).join('، ') + ` · میانگین ${FA(r.days)} روز اخیر`;
  }

  // competitors page: the accounts to look up with Business Discovery
  async function loadHandles() {
    const ta = $('comp-handles'); if (!ta) return;
    try {
      const r = await api('GET', '/api/me/competitors/handles');
      ta.value = r.handles.join('\n');
      const m = $('comp-handles-msg');
      m.textContent = !r.connected ? 'برای گرفتن آمارشون، اتصال Facebook رو تو تنظیمات وصل کن.' : r.problems.length ? 'پیدا نشدن: ' + r.problems.join(' · ') : '';
      m.style.color = r.problems.length ? 'var(--coral)' : '';
    } catch (e) { /* not in the panel */ }
  }
  const hs = $('comp-handles-save');
  if (hs) hs.addEventListener('click', async () => {
    hs.disabled = true;
    try {
      const r = await api('POST', '/api/me/competitors/handles', { handles: $('comp-handles').value.split(/[\s,،]+/).filter(Boolean) });
      say($('comp-handles-msg'), r.message);
    } catch (e) { say($('comp-handles-msg'), e.message, true); }
    hs.disabled = false;
  });

  // the board's cards send their hook and notes here
  window.sjPublish = {
    open(card) {
      $('pub-caption').value = [card.hook, card.notes].filter(Boolean).join('\n\n');
      $('pub-caption').dispatchEvent(new Event('input'));
      if (card.text) { $('cover-text').value = card.text; drawCover(); }
      sec.dataset.card = card.id || '';
      location.hash = '#/publish';
    },
  };
  window.addEventListener('sj:page', (e) => {
    if (e.detail.page === 'publish') { loadQueue(); bestHours(); syncGo(); } else clearTimeout(poll);
    if (e.detail.page === 'besttime') drawOnline();
    if (e.detail.page === 'competitors') loadHandles();
  });
})();
