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
    if (data.error && NOTE[data.error] && !data.posts.length) {
      list.innerHTML = window.vfEmpty('i-comment', data.error === 'permission' ? 'اجازهٔ خوندن کامنت‌ها نیست' : 'هنوز کامنتی نیومده', NOTE[data.error], '<a class="sj-btn" href="/settings#conns-card">تنظیمات اتصال‌ها</a>');
      return;
    }
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
              ${c.answered ? '<span class="sj-chip sj-ok">جواب دادی</span>' : ''}
              ${c.id ? `<button type="button" class="sj-chip-btn" data-reply="${esc(c.id)}">جواب</button><button type="button" class="sj-chip-btn" data-hide="${esc(c.id)}" aria-label="پنهان کردن این کامنت">پنهان</button>` : igUrl(p.url) ? `<a class="sj-chip sj-chip-link" href="${esc(p.url)}" target="_blank" rel="noopener">جواب بده</a>` : ''}</div>
            <p>${esc(c.text)}</p>
            <div class="sj-reply-box" data-box="${esc(c.id || '')}" hidden>
              <textarea rows="2" maxlength="2000" aria-label="متن جواب به @${esc(c.user || '')}"></textarea>
              <div class="sj-row-btns"><button type="button" class="sj-btn sj-btn-primary" data-send="public">جواب زیر کامنت</button>
                <button type="button" class="sj-btn" data-send="private" title="اینستاگرام فقط یک پیام خصوصی برای هر کامنت و تا ۷ روز اجازه می‌ده">پیام خصوصی</button>
                <button type="button" class="sj-btn" data-send="cancel">بی‌خیال</button></div>
              <p class="sj-small" data-out role="status"></p>
            </div>
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
  // answering from the panel: a public reply, the one private reply Instagram allows, or hiding
  list.addEventListener('click', async (e) => {
    const r = e.target.closest('[data-reply]');
    if (r) { const box = list.querySelector(`[data-box="${r.dataset.reply}"]`); box.hidden = !box.hidden; if (!box.hidden) box.querySelector('textarea').focus(); return; }
    const h = e.target.closest('[data-hide]');
    if (h) {
      if (!confirm('این کامنت پنهان بشه؟ (فقط خود نویسنده‌اش می‌بینه)')) return;
      h.disabled = true;
      try { await api('POST', '/api/me/comments/reply', { comment_id: h.dataset.hide, how: 'hide' }); h.closest('.sj-comment').classList.add('sj-hidden-c'); h.textContent = 'پنهان شد'; }
      catch (err) { alert(err.message); h.disabled = false; }
      return;
    }
    const s = e.target.closest('[data-send]'); if (!s) return;
    const box = s.closest('.sj-reply-box'), out = box.querySelector('[data-out]');
    if (s.dataset.send === 'cancel') { box.hidden = true; return; }
    const text = box.querySelector('textarea').value.trim();
    if (!text) { out.textContent = 'متن جواب خالیه'; return; }
    s.disabled = true;
    try {
      const res = await api('POST', '/api/me/comments/reply', { comment_id: box.dataset.box, text, how: s.dataset.send });
      out.textContent = res.message; out.style.color = '';
      if (s.dataset.send === 'public') setTimeout(load, 800);
    } catch (err) { out.textContent = err.message; out.style.color = 'var(--coral)'; }
    s.disabled = false;
  });

  // keyword automation
  let auto = null;
  const rulesBox = $('auto-rules');
  function drawRules() {
    if (!auto) return;
    $('auto-save').hidden = !auto.rules.length;
    if (!auto.rules.length) { rulesBox.innerHTML = '<p class="sj-note">قانونی نداری. «قانون تازه» رو بزن.</p>'; }
    else rulesBox.innerHTML = auto.rules.map((r, i) => `
      <fieldset class="sj-rule" data-i="${i}">
        <legend>قانون ${i + 1}${r.count ? ` · ${r.count} پیام فرستاده` : ''}</legend>
        <label class="sj-field">ریل<select data-k="media_id"><option value="">— انتخاب کن —</option>${auto.reels.map((m) => `<option value="${esc(m.id)}"${m.id === r.media_id ? ' selected' : ''}>${esc(m.label)}</option>`).join('')}
          ${r.media_id && !auto.reels.some((m) => m.id === r.media_id) ? `<option value="${esc(r.media_id)}" selected>${esc(r.label || r.media_id)}</option>` : ''}</select></label>
        <label class="sj-field">کلمهٔ کلیدی<input data-k="keyword" value="${esc(r.keyword)}" maxlength="40" placeholder="مثلاً: پرامپت"></label>
        <label class="sj-field">پیام خصوصی<textarea data-k="message" rows="3" maxlength="900" placeholder="سلام! اینم لینکی که گفتم: …">${esc(r.message)}</textarea></label>
        <label class="sj-check"><input type="checkbox" data-k="public_reply"${r.public_reply ? ' checked' : ''}> یه جواب کوتاه هم زیر کامنت بذار («دایرکتت رو چک کن 🙌»)</label>
        <label class="sj-check"><input type="checkbox" data-k="active"${r.active ? ' checked' : ''}> فعال</label>
        <button type="button" class="sj-btn" data-del="${i}">حذف قانون</button>
      </fieldset>`).join('');
    $('auto-log').innerHTML = auto.log.length ? auto.log.map((l) => `<p class="sj-small">${esc(when(new Date(l.at * 1000).toISOString()))} · @${esc(l.user || '?')} · «${esc(l.comment || '')}» · ${l.ok ? 'فرستاده شد ✓' : esc(l.error || 'نشد')}</p>`).join('') : '<p class="sj-small">هنوز پیامی فرستاده نشده.</p>';
  }
  const readRules = () => [...rulesBox.querySelectorAll('.sj-rule')].map((f) => {
    const r = { ...auto.rules[Number(f.dataset.i)] };
    f.querySelectorAll('[data-k]').forEach((el) => { r[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value; });
    const sel = f.querySelector('[data-k="media_id"]');
    r.label = sel.selectedOptions[0] ? sel.selectedOptions[0].textContent.trim() : '';
    return r;
  });
  async function loadAuto() {
    try { auto = await api('GET', '/api/me/ig/auto'); drawRules(); } catch (e) { rulesBox.innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; }
  }
  $('auto-add').addEventListener('click', () => {
    if (!auto) return;
    auto.rules = [...readRules(), { media_id: '', keyword: '', message: '', public_reply: true, active: true }];
    drawRules();
    rulesBox.lastElementChild.querySelector('select').focus();
  });
  rulesBox.addEventListener('click', (e) => {
    const d = e.target.closest('[data-del]'); if (!d) return;
    const rules = readRules(); rules.splice(Number(d.dataset.del), 1); auto.rules = rules; drawRules(); $('auto-save').hidden = false;
  });
  $('auto-save').addEventListener('click', async (e) => {
    const b = e.currentTarget; b.disabled = true;
    try { const r = await api('POST', '/api/me/ig/auto', { rules: readRules() }); auto.rules = r.rules; drawRules(); $('auto-msg').textContent = 'ذخیره شد ✓'; $('auto-msg').style.color = ''; }
    catch (err) { $('auto-msg').textContent = err.message; $('auto-msg').style.color = 'var(--coral)'; }
    b.disabled = false;
  });

  window.addEventListener('sj:page', (e) => { if (e.detail.page === 'comments') { load(); loadAuto(); } });
})();
