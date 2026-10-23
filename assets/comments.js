/* Comments page (#/comments): the last 30 days of comments from the Instagram connection, which ones
   are still unanswered, and an AI read of what the audience is saying (questions with suggested
   replies, reel ideas). Needs the panel, like tools.js. */
(function () {
  const list = document.getElementById('comments-list');
  if (!list) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const code = (url) => (String(url).match(/\/(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/) || [])[1] || '';
  const igUrl = (u) => (/^https:\/\/(www\.)?instagram\.com\//.test(u || '') ? u : '');
  const jWhen = new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tehran' });
  const when = (t) => { try { return t ? jWhen.format(new Date(t)) : ''; } catch (e) { return ''; } };
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

  let data = null, filter = 'all';
  const NOTE = {
    none: 'هنوز کامنتی گرفته نشده. Instagram API رو تو «تنظیمات ← اتصال‌ها» وصل کن؛ کامنت‌ها با گرفتن دادهٔ بعدی میان.',
    permission: 'توکن اینستاگرامت اجازهٔ خوندن کامنت‌ها رو نداره. یه توکن تازه با دسترسی instagram_business_manage_comments بساز و تو تنظیمات بذار.',
  };

  function drawList() {
    if (!data) return;
    if (data.error && NOTE[data.error] && !data.posts.length) { list.innerHTML = `<p class="sj-note">${esc(NOTE[data.error])}</p>`; return; }
    const posts = data.posts.map((p) => ({ ...p, shown: p.comments.filter((c) => filter === 'all' || !c.answered) })).filter((p) => p.shown.length);
    if (!posts.length) { list.innerHTML = `<p class="sj-note">${filter === 'open' ? 'همهٔ کامنت‌ها جواب گرفتن ✓' : 'تو ۳۰ روز اخیر کامنتی نیومده.'}</p>`; return; }
    list.innerHTML = posts.map((p) => `
      <div class="sj-cpost">
        <div class="sj-cpost-head">
          <a href="#/reel/${esc(code(p.url))}">${esc((p.caption || '').split('\n')[0].slice(0, 80) || 'ریل')}</a>
          <span class="sj-chip">${p.comments.length} کامنت</span>${p.unanswered ? `<span class="sj-chip sj-late">${p.unanswered} بی‌جواب</span>` : ''}
        </div>
        ${p.shown.map((c) => `
          <div class="sj-comment${c.answered ? '' : ' open'}">
            <div class="sj-comment-top"><b dir="ltr">@${esc(c.user || '?')}</b><span class="sj-small">${esc(when(c.at))}${c.likes ? ' · ' + c.likes + ' لایک' : ''}</span>
              ${c.answered ? '<span class="sj-chip sj-ok">جواب دادی</span>' : igUrl(p.url) ? `<a class="sj-chip sj-chip-link" href="${esc(p.url)}" target="_blank" rel="noopener">جواب بده</a>` : ''}</div>
            <p>${esc(c.text)}</p>
          </div>`).join('')}
      </div>`).join('');
  }

  function drawAnalysis(a) {
    const box = $('comments-analysis');
    if (!a) return;
    const date = a.created ? new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { day: 'numeric', month: 'long' }).format(new Date(a.created * 1000)) : '';
    box.innerHTML = `
      <p class="sj-small">از روی ${a.comments || 0} کامنت${date ? '، ' + esc(date) : ''}</p>
      <div class="sj-crit"><h4>خلاصه</h4><p>${esc(a.summary)}</p><p class="sj-small">${esc(a.mood)}</p></div>
      ${a.themes && a.themes.length ? `<div class="sj-crit"><h4>موضوع‌های پرتکرار</h4><ul>${a.themes.map((t) => `<li><b>${esc(t.theme)}</b>: ${esc(t.detail)}</li>`).join('')}</ul></div>` : ''}
      ${a.questions && a.questions.length ? `<div class="sj-crit"><h4>سؤال‌ها و پیشنهاد جواب</h4>${a.questions.map((q) => `
        <div class="sj-out-row"><div><p><b>${esc(q.question)}</b></p><p class="sj-small">${esc(q.reply)}</p></div>
          <button type="button" class="sj-btn sj-copy" data-copy="${esc(q.reply)}">کپی جواب</button></div>`).join('')}</div>` : ''}
      ${a.ideas && a.ideas.length ? `<div class="sj-crit"><h4>ایدهٔ ریل از دل کامنت‌ها</h4><ul>${a.ideas.map((i) => `<li>${esc(i)} <button type="button" class="sj-linkbtn" data-idea="${esc(i)}">به بُرد</button></li>`).join('')}</ul></div>` : ''}`;
  }

  async function load() {
    try { data = await api('GET', '/api/me/comments'); } catch (e) { list.innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; return; }
    drawList();
    drawAnalysis(data.analysis);
    $('comments-analyze').textContent = data.analysis ? 'تحلیل تازه' : 'تحلیل با هوش مصنوعی';
  }

  document.querySelector('#comments [aria-label="فیلتر"]').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cfilter]'); if (!b) return;
    filter = b.dataset.cfilter;
    b.parentElement.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    drawList();
  });
  $('comments-analyze').addEventListener('click', async (e) => {
    const b = e.currentTarget, label = b.textContent;
    b.disabled = true; b.textContent = 'صبر کن…';
    $('comments-analysis').innerHTML = '<div class="sj-msg ai sj-typing"><span></span><span></span><span></span></div>';
    try { drawAnalysis(await api('POST', '/api/me/comments/analyze')); b.textContent = 'تحلیل تازه'; }
    catch (err) { $('comments-analysis').innerHTML = `<p class="sj-error">${esc(err.message)}</p>`; b.textContent = label; }
    b.disabled = false;
  });
  $('comments-analysis').addEventListener('click', async (e) => {
    const c = e.target.closest('.sj-copy');
    if (c) { try { await navigator.clipboard.writeText(c.dataset.copy); c.textContent = 'کپی شد ✓'; setTimeout(() => { c.textContent = 'کپی جواب'; }, 1500); } catch (err) { /* no clipboard */ } }
    const i = e.target.closest('[data-idea]');
    if (i && window.sjBoard) {
      i.disabled = true;
      try { await window.sjBoard.add({ title: i.dataset.idea, notes: 'از کامنت‌ها' }); i.textContent = 'اضافه شد ✓'; } catch (err) { i.textContent = 'اضافه نشد'; i.disabled = false; }
    }
  });
  window.addEventListener('sj:page', (e) => { if (e.detail.page === 'comments') load(); });
})();
