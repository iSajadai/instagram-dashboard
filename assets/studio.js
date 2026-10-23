/* Content studio (#/studio): the 13 Persian agents (adapted from instagram-agent-skill). Each has a
   small form and its own result view; the server runs the model and then the Persian tools (hook
   scores, beat timing, caption lint, humanizer) on what it wrote. Nothing is posted from here. */
(function () {
  const root = document.getElementById('studio-body');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fa = (n) => (n == null ? '—' : Number(n).toLocaleString('fa-IR', { maximumFractionDigits: 1 }));
  async function api(method, path, body) {
    const r = await fetch(path, { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'sajadai', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
    let d = {};
    try { d = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'خطا (' + r.status + ')');
    return d;
  }
  let meta = null;
  const formulaOptions = () => '<option value="">خودش انتخاب کنه</option>' + (meta ? meta.formulas.map((f) => `<option value="${f.id}">#${fa(f.id)} ${esc(f.name)}</option>`).join('') : '');

  // ---------- the agents and their forms ----------
  const A = {
    reel: { icon: '🎬', title: 'ریل‌ساز', desc: 'از یه ایده: سه هوک از ۲۶ فرمول با امتیاز، فیلمنامه، متن روی صفحه و زمان‌بندی صحنه‌ها.',
      fields: [['idea', 'ایدهٔ ریل (یه اتفاق واقعی، با عدد اگه داری)', 'area'], ['length', 'طول هدف (ثانیه)', 'num', '30'], ['formula', 'فرمول هوک', 'formula']] },
    caption: { icon: '✍️', title: 'کپشن‌نویس', desc: 'کپشن با ۱۲۵ حرف اول درست، یه درخواست، تا ۵ هشتگ، بررسی‌شده با لینتر فارسی.',
      fields: [['about', 'این پست/ریل دربارهٔ چیه (یا فیلمنامه‌اش)', 'area'], ['job', 'نوع', 'select', '', [['auto', 'خودش تشخیص بده'], ['A', 'ریل خودش هوک داره'], ['B', 'کپشن خودش محتواست']]], ['keywords', 'عبارت‌هایی که می‌خوای باهاش پیدا بشی (با ویرگول)', 'text']] },
    carousel: { icon: '🗂️', title: 'کاروسل‌ساز', desc: 'کاور، متن اسلایدها، اسلاید جمع‌بندی و کپشن؛ با فایل‌های ۱۰۸۰×۱۳۵۰ آمادهٔ آپلود.',
      fields: [['idea', 'ایده (مرحله‌ها، چارچوب، قبل/بعد، فهرست)', 'area'], ['keywords', 'عبارت‌های جست‌وجو', 'text']] },
    story: { icon: '⭕', title: 'استوری‌نویس', desc: 'استوری‌های امروز فریم به فریم، کدوم استیکر کجا، و قیف دایرکتی که اول خودشون شروع می‌کنن.',
      fields: [['today', 'امروز چی شد / چی داری', 'area'], ['goal', 'هدف', 'select', '', [['ارتباط', 'ارتباط'], ['فروش', 'فروش'], ['ایده گرفتن از مخاطب', 'ایده گرفتن از مخاطب'], ['معرفی محصول', 'معرفی محصول']]], ['offer', 'محصول یا پیشنهاد (اگه هست)', 'text']] },
    viral: { icon: '🔎', title: 'تحقیق وایرال', desc: 'ریل‌هایی که تو حوزه‌ات جواب دادن رو با «چند برابر میانهٔ همون پیج» رتبه می‌ده، فرمولشون رو اسم می‌بره و نسخهٔ خودت رو می‌نویسه.',
      fields: [['niche', 'حوزه', 'text'], ['rows', 'ریل‌ها: هر خط «آیدی، فالوئر، میانهٔ بازدید ریل‌هاش، بازدید این ریل، هوک»', 'area', '@page_a\t48000\t11000\t412000\tهیچ‌کس بهت نمی‌گه ۳۰ ریل اولت قراره شکست بخوره']] },
    plan: { icon: '🗓️', title: 'برنامه‌ریز هفته', desc: 'هفته از شنبه: چی، چه قالبی، چه ساعتی (از آمار خودت)، با فرمول هوک؛ و ۱۰ حساب برای تعامل.',
      fields: [['happened', 'این هفته واقعاً چی شد (تماس، عدد، اشتباه، چیزی که ساختی)', 'area'], ['sells', 'چی می‌فروشی و به کی', 'text'], ['themes', '۳-۴ موضوعی که می‌خوای بهش شناخته بشی', 'text'], ['accounts', 'حساب‌هایی که می‌خوای دیده بشی (اختیاری)', 'area']] },
    audit: { icon: '🩺', title: 'کالبدشکافی پست‌ها', desc: 'ریل‌های خودت با عددهای واقعی: چند برابر میانه، ماندن ۳ ثانیه، اشتراک و فالو به ازای reach. چی رو قطع کنی، چی رو بیشتر.',
      fields: [] },
    profile: { icon: '🪪', title: 'پروفایل‌سنج', desc: 'پروفایلت از ۱۰۰ با چک‌لیست ۱۲ بخشی، و بازنویسی بخش‌هایی که امتیاز از دست دادن.',
      fields: [['name_field', 'فیلد نام (خط پررنگ زیر عکس)', 'text'], ['handle', 'آیدی', 'text'], ['bio', 'بایو', 'area'], ['link', 'لینک به کجا می‌ره', 'text'],
        ['highlights', 'اسم هایلایت‌ها', 'text'], ['pinned', 'پست‌های پین‌شده', 'text'], ['grid', 'نه کاور اول گرید چی نشون می‌دن', 'area'], ['photo', 'عکس پروفایل', 'text'],
        ['category', 'نوع اکانت و دسته‌بندی', 'text'], ['activity', 'آخرین پست و استوری کی بود', 'text']] },
    human: { icon: '🧑', title: 'آدمی‌کن', desc: 'ردپای ماشین رو پاک می‌کنه (نیم‌فاصله رو نگه می‌داره و درست می‌کنه) و با پنج سنجه امتیاز می‌ده.',
      fields: [['text', 'متن (کپشن، فیلمنامه، کامنت، دایرکت)', 'area'], ['rewrite', 'خطوط علامت‌دار رو هم با هوش مصنوعی بازنویسی کن', 'check']] },
    comment: { icon: '💬', title: 'کامنت‌نویس', desc: 'کامنت روی پست بقیه که آدم با نظر بنویسه، نه ربات: دو گزینه از ۹ نوع.',
      fields: [['posts', 'متن پست یا ریل (چندتا؟ با یه خط --- جدا کن)', 'area']] },
    reply: { icon: '↩️', title: 'جواب کامنت', desc: 'کامنت‌های پست خودت رو دسته‌بندی می‌کنه (کلمهٔ کلیدی، مشتری، سؤال، …) و به ترتیب ارزش جواب می‌نویسه.',
      fields: [['comments', 'کامنت‌ها، هر خط یکی (با آیدی)', 'area']], extra: '<button type="button" class="sj-btn" id="reply-load">از کامنت‌های بی‌جواب خودم</button>' },
    dm: { icon: '✉️', title: 'دایرکت‌نویس', desc: 'تحویل کلمهٔ کلیدی، پیام اول به آشنا، پیشنهاد همکاری، و دو پیگیری؛ فقط وقتی اول خودشون حرکت کردن.',
      fields: [['kind', 'نوع', 'select', '', [['keyword', 'تحویل کلمهٔ کلیدی'], ['warm', 'پیام به آشنا'], ['collab', 'پیشنهاد همکاری'], ['cold', 'سرد (توصیه نمی‌شه)']]],
        ['who', 'به کی (آیدی، چی کار می‌کنه)', 'text'], ['trigger', 'دلیل پیام امروز (کامنتی که گذاشت، استوری‌ای که جواب داد…)', 'text'], ['want', 'چی می‌خوای', 'text'], ['thing', 'چیزی که قول دادی / لینکش', 'text']] },
    repurpose: { icon: '♻️', title: 'بازنشر', desc: 'یه ویدیو، پادکست یا مقالهٔ بلند رو می‌کنه یه هفته ریل و کاروسل که هر کدوم تنها وایمیستن.',
      fields: [['title', 'عنوان منبع', 'text'], ['source', 'متن کامل (ترنسکریپت، مقاله، یادداشت)', 'area']] },
  };
  const ORDER = ['reel', 'caption', 'carousel', 'story', 'viral', 'plan', 'audit', 'profile', 'human', 'comment', 'reply', 'dm', 'repurpose'];

  function field([key, label, type, ph, opts]) {
    const id = 'sf-' + key;
    if (type === 'area') return `<label>${esc(label)}<textarea id="${id}" data-k="${key}" rows="${key === 'source' ? 10 : 5}" placeholder="${esc(ph || '')}"></textarea></label>`;
    if (type === 'check') return `<label class="sj-check"><input type="checkbox" id="${id}" data-k="${key}"> ${esc(label)}</label>`;
    if (type === 'select') return `<label>${esc(label)}<select id="${id}" data-k="${key}">${opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></label>`;
    if (type === 'formula') return `<label>${esc(label)}<select id="${id}" data-k="${key}">${formulaOptions()}</select></label>`;
    return `<label>${esc(label)}<input id="${id}" data-k="${key}" ${type === 'num' ? 'type="number" dir="ltr"' : ''} value="${esc(type === 'num' ? ph : '')}" placeholder="${type === 'num' ? '' : esc(ph || '')}"></label>`;
  }

  let current = null;
  function open(agent, prefill) {
    current = agent;
    const a = A[agent];
    location.hash = '#/studio/' + agent;
    $('studio-form-card').hidden = false;
    $('studio-form-title').textContent = a.icon + ' ' + a.title;
    $('studio-form-desc').textContent = a.desc;
    $('studio-fields').innerHTML = a.fields.map(field).join('') + (a.extra || '');
    Object.entries(prefill || {}).forEach(([k, v]) => { const el = $('sf-' + k); if (el) { if (el.type === 'checkbox') el.checked = !!v; else el.value = v; } });
    $('studio-result').innerHTML = '';
    $('studio-run').textContent = agent === 'audit' ? 'کالبدشکافی کن' : 'بنویس';
    document.querySelectorAll('.sj-agent').forEach((c) => c.classList.toggle('is-on', c.dataset.agent === agent));
    if (agent === 'reply' && $('reply-load')) {
      $('reply-load').addEventListener('click', () => loadMyComments(false));
      if (!prefill) loadMyComments(true);  // coming from the comments page: start with the unanswered ones
    }
    $('studio-form-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  async function loadMyComments(quiet) {
    try {
      const d = await api('GET', '/api/me/comments');
      const lines = [];
      (d.posts || []).forEach((p) => p.comments.filter((c) => !c.answered).forEach((c) => lines.push('@' + (c.user || '?') + ': ' + c.text.replace(/\n/g, ' '))));
      if (lines.length || !quiet) $('sf-comments').value = lines.join('\n');
      if (!lines.length && !quiet) alert('کامنت بی‌جوابی پیدا نشد (یا کامنت‌ها هنوز گرفته نشدن).');
    } catch (e) { if (!quiet) alert(e.message); }
  }

  async function runAgent() {
    const input = {};
    document.querySelectorAll('#studio-fields [data-k]').forEach((el) => { input[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value.trim(); });
    const btn = $('studio-run'), label = btn.textContent;
    btn.disabled = true; btn.textContent = 'داره می‌نویسه…';
    $('studio-result').innerHTML = '<div class="sj-msg ai sj-typing"><span></span><span></span><span></span></div>';
    try {
      const out = await api('POST', '/api/me/studio/' + current, { input });
      render(current, out, input);
    } catch (e) { $('studio-result').innerHTML = `<p class="sj-error">${esc(e.message)}</p>`; }
    btn.disabled = false; btn.textContent = label;
  }

  // ---------- pieces shared by the result views ----------
  const copy = (text, label) => `<button type="button" class="sj-btn sj-copy" data-copy="${esc(text)}">${label || 'کپی'}</button>`;
  const badge = (s, kind) => {
    if (!s) return '';
    const v = s.verdict;
    const cls = { STRONG: 'ok', PASS: 'ok', READY: 'ok', OK: 'mid', REVIEW: 'mid', WEAK: 'bad', FLAGGED: 'bad', FIX: 'bad' }[v] || 'mid';
    return `<span class="sj-score ${cls}" title="${esc(kind || '')}">${s.overall != null ? fa(Math.round(s.overall)) + ' · ' : ''}${esc(s.verdict_fa || v)}</span>`;
  };
  const checks = (s) => s ? `<div class="sj-checks">${s.checks.map((c) => `<div class="sj-checkrow"><span>${esc(c.name)}</span><i class="sj-meter"><b style="width:${Math.round(c.score)}%"></b></i><small>${esc(c.detail)}</small></div>`).join('')}</div>` : '';
  const lintRows = (l) => `<div class="sj-lint">${l.checks.map((c) => `<div class="sj-lintrow ${c.status.toLowerCase()}"><b>${{ PASS: '✓', WARN: '!', FAIL: '✗' }[c.status]}</b><span>${esc(c.check)}</span><small>${esc(c.detail)}</small></div>`).join('')}</div>`;
  const flags = (fl) => fl && fl.length ? `<div class="sj-flags"><h4>الگوهای ماشینی که باید دستی بازنویسی بشن</h4>${fl.map((f) => `<p><b>${esc(f.name)}</b>${f.example ? ' — «' + esc(f.example) + '»' : ''}<br><small>${esc(f.fix)}</small></p>`).join('')}</div>` : '';
  const warns = (w) => w && w.length ? `<ul class="sj-warns">${w.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  const toBoard = (title, hook, notes) => `<button type="button" class="sj-btn" data-board="${esc(JSON.stringify({ title, hook, notes }))}">به بُرد تولید</button>`;
  const chain = (agent, prefill, label) => `<button type="button" class="sj-btn" data-chain="${agent}" data-prefill="${esc(JSON.stringify(prefill))}">${esc(label)}</button>`;
  const box = (title, inner) => `<div class="sj-crit"><h4>${esc(title)}</h4>${inner}</div>`;

  function captionBlock(c) {
    return box('کپشن' + (c.job ? ' · نوع ' + (c.job === 'A' ? 'الف (ریل خودش هوک داره)' : 'ب (کپشن خودش محتواست)') : ''),
      `<p class="sj-small">${esc(c.why_job || '')}</p>
       <div class="sj-feed"><div class="sj-feed-cut">${esc(c.lint.visible)}${c.lint.truncated ? '<span>... بیشتر</span>' : ''}</div><small>این بخشیه که تو فید دیده می‌شه</small></div>
       <div class="sj-out-row"><p style="white-space:pre-line">${esc(c.caption)}</p>${copy(c.caption)}</div>
       <div class="sj-tools">${badge(c.lint, 'لینتر کپشن')} ${badge(c.human, 'آدمی بودن')}</div>${lintRows(c.lint)}
       ${c.alt_text ? `<p class="sj-small"><b>متن جایگزین (Alt):</b> ${esc(c.alt_text)} ${copy(c.alt_text)}</p>` : ''}
       ${c.first_comment ? `<p class="sj-small"><b>کامنت اول:</b> ${esc(c.first_comment)} ${copy(c.first_comment)}</p>` : ''}${flags(c.flags)}`);
  }

  // ---------- result views ----------
  const R = {
    reel(o, inp) {
      const best = o.hooks[0] || {};
      return (o.thin ? `<p class="sj-error">ایده نازکه: ${esc(o.question)}</p>` : '') + (o.two_ideas ? `<p class="sj-error">${esc(o.two_ideas)}</p>` : '') +
        box('هوک‌ها (امتیازدار)', o.hooks.map((h) => `<div class="sj-hook">${badge(h.score)}<div><b>#${fa(h.formula_id)} ${esc(h.formula)}</b><p>«${esc(h.spoken)}»</p>
          <small>روی صفحه: ${esc(h.on_screen)}</small>${h.score && h.score.flags.length ? `<small class="sj-bad">${esc(h.score.flags.join(' '))}</small>` : ''}
          ${h.score ? `<details><summary>جزئیات امتیاز</summary>${checks(h.score)}</details>` : ''}</div>${copy(h.spoken)}</div>`).join('') + (o.why ? `<p class="sj-small">${esc(o.why)}</p>` : '')) +
        box('زمان‌بندی صحنه‌ها · ' + fa(o.beats.total) + ' ثانیه، ' + fa(o.beats.words) + ' کلمه با ' + fa(o.beats.wpm) + ' کلمه در دقیقه',
          `<table class="sj-table sj-beats"><tbody>${o.beats.beats.map((b) => `<tr class="${b.long ? 'long' : ''}"><td dir="ltr">${fa(Math.floor(b.start / 60))}:${String(Math.floor(b.start % 60)).padStart(2, '0').replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d])}</td><td>${fa(b.secs)}ث</td><td>${esc(b.label || '')}</td><td>${esc(b.text)}</td></tr>`).join('')}</tbody></table>${warns(o.beats.flags)}`) +
        box('متن روی صفحه', `<ul>${o.cards.map((c) => `<li>صحنهٔ ${fa(c.beat)}: <b>${esc(c.text)}</b></li>`).join('')}</ul>`) +
        `<div class="sj-tools">${badge(o.human, 'آدمی بودن فیلمنامه')}${copy(o.script.join('\n'), 'کپی فیلمنامه')}${toBoard(inp.idea.slice(0, 80), best.spoken || '', o.script.join('\n'))}
          ${chain('caption', { about: o.script.join('\n'), job: 'A' }, 'نوشتن کپشن این ریل')}</div>${flags(o.flags)}`;
    },
    caption: (o) => captionBlock(o),
    carousel(o) {
      return (!o.is_carousel ? `<p class="sj-error">${esc(o.redirect_note)}</p>` : '') +
        box(fa(o.slides.length) + ' اسلاید', `<ol class="sj-slides">${o.slides.map((s) => `<li><small>${{ cover: 'کاور', stake: 'چرا مهمه', idea: 'ایده', recap: 'جمع‌بندی', cta: 'درخواست' }[s.role]}</small><b>${esc(s.headline)}</b><p>${esc(s.body)}</p></li>`).join('')}</ol>${warns(o.warnings)}
          <div class="sj-tools"><button type="button" class="sj-btn sj-btn-primary" id="carousel-png">دانلود اسلایدها (PNG ۱۰۸۰×۱۳۵۰)</button></div>`) + captionBlock(o.caption);
    },
    story(o) {
      const ST = { none: '', poll: 'نظرسنجی', question: 'جعبهٔ سؤال', quiz: 'کوییز', slider: 'اسلایدر', link: 'لینک', countdown: 'شمارش معکوس', add_yours: 'نوبت تو' };
      return box('استوری‌های امروز · ' + fa(o.frames.length) + ' فریم', `<ol class="sj-frames">${o.frames.map((f) => `<li><small>${esc(f.visual)}</small>
        ${f.on_screen ? `<b>${esc(f.on_screen)}</b>` : ''}${f.said ? `<p>«${esc(f.said)}»</p>` : ''}${f.sticker !== 'none' ? `<span class="sj-chip">${ST[f.sticker]}: ${esc(f.sticker_text)}${f.options.length ? ' (' + f.options.map(esc).join(' / ') + ')' : ''}</span>` : ''}</li>`).join('')}</ol>`) +
        box('بعدش', `<p>${esc(o.after)}</p>`) + warns(o.warnings);
    },
    viral(o) {
      return box(`سوایپ · ${fa(o.n)} ریل از ${fa(o.accounts)} حساب · ${esc(o.confidence)}`,
        `<table class="sj-table"><thead><tr><th>چند برابر</th><th>هوک</th><th>فرمول</th><th>امتیاز هوک</th><th>حساب</th></tr></thead><tbody>${o.ranked.slice(0, 25).map((r) => `<tr><td>${fa(r.multiple)}×</td><td>${esc(r.hook)}</td><td>${r.formula_id ? '#' + fa(r.formula_id) + ' ' + esc(r.formula) : '<span class="sj-bad">بی‌نام</span>'}</td><td>${fa(r.hook_score)}</td><td dir="ltr">${esc(r.account)}</td></tr>`).join('')}</tbody></table>
         <p class="sj-small">طول هوک (کلمه): یک‌سوم بالا ${fa(o.hook_words.top)}، یک‌سوم پایین ${fa(o.hook_words.bottom)}</p>`) +
        box('چی معنی می‌ده', `<ul>${o.findings.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>${o.unclassified_note ? `<p class="sj-small">${esc(o.unclassified_note)}</p>` : ''}`) +
        box('نسخهٔ خودت', o.your_versions.map((v) => `<div class="sj-hook">${badge(v.score)}<div><b>#${fa(v.formula_id)} ${esc(v.formula)}</b><p>«${esc(v.hook)}»</p><small>${esc(v.why)}</small></div>
          ${chain('reel', { idea: v.hook, formula: v.formula_id }, 'ریلش رو بنویس')}</div>`).join(''));
    },
    plan(o) {
      const K = { reel: 'ریل', carousel: 'کاروسل', stories: 'فقط استوری', engage: 'فقط تعامل', off: 'استراحت' };
      const T = { proof: 'مدرک', teach: 'آموزش', opinion: 'نظر', story: 'داستان', offer: 'پیشنهاد', none: '' };
      return box('هفته', `<table class="sj-table"><tbody>${o.days.map((d) => `<tr><td><b>${esc(d.day)}</b></td><td>${d.time ? esc(d.time) : ''}</td><td>${K[d.kind]}</td><td>${T[d.type]}</td>
        <td>${d.formula ? '#' + fa(d.formula_id) + ' ' + esc(d.formula) : ''}</td><td>${esc(d.angle)}${d.hook ? `<br><small>«${esc(d.hook)}»</small>` : ''}</td>
        <td>${['reel', 'carousel'].includes(d.kind) ? toBoard(d.angle.slice(0, 80), d.hook, d.day + ' ' + (d.time || '') + ' · ' + K[d.kind]) : ''}</td></tr>`).join('')}</tbody></table>${warns(o.warnings)}`) +
        box('استوری و ساعت', `<p>${esc(o.stories_note)}</p><p class="sj-small">${esc(o.timing_note)}</p>`) +
        box('تعامل روزانه (۲۰ دقیقه، قبل از پست)', ['reach', 'peers', 'buyers'].map((k) => `<p><b>${{ reach: 'دیده‌شدن', peers: 'هم‌سطح‌ها', buyers: 'خریدارها' }[k]}:</b> ${o.engage[k].map(esc).join('، ')}</p>`).join(''));
    },
    audit(o) {
      const row = (r) => `<tr><td>${fa(r.multiple)}×</td><td>${esc((r.hook || '').slice(0, 70))}</td><td>${fa(r.hold_3s)}٪</td><td>${fa(r.sends_per_1k_reach)}</td><td>${fa(r.follows_per_1k_reach)}</td><td>${r.formula ? esc(r.formula) : '—'}</td></tr>`;
      const head = '<thead><tr><th>چند برابر</th><th>هوک</th><th>ماندن ۳ث</th><th>اشتراک/۱۰۰۰</th><th>فالو/۱۰۰۰</th><th>فرمول</th></tr></thead>';
      return box(`کالبدشکافی · ${fa(o.n)} ریل · میانهٔ بازدید ${fa(o.median_views)} · ${esc(o.confidence)}`,
        `<h4>بالاترین‌ها</h4><table class="sj-table">${head}<tbody>${o.top.map(row).join('')}</tbody></table>
         ${o.bottom.length ? `<h4>پایین‌ترین‌ها</h4><table class="sj-table">${head}<tbody>${o.bottom.map(row).join('')}</tbody></table>` : ''}`) +
        box('دیتا چی می‌گه', `<ol>${o.findings.map((f) => `<li><b>${esc(f.claim)}</b><br><small>${esc(f.evidence)} · اطمینان: ${esc(f.confidence)}</small></li>`).join('')}</ol>
          ${o.profile_problem ? '<p class="sj-error">بازدید داری ولی فالو نه: مشکل از پروفایله، نه هوک. برو سراغ پروفایل‌سنج.</p>' : ''}
          <p><b>دیگه نساز:</b> ${esc(o.stop)}</p><p><b>بیشتر بساز:</b> ${esc(o.do_more)}</p>${o.note ? `<p class="sj-small">${esc(o.note)}</p>` : ''}`);
    },
    profile(o) {
      return box(`امتیاز پروفایل ${fa(o.total)} از ۱۰۰ → بعد از بازنویسی حدود ${fa(o.total_after)}`,
        `<table class="sj-table"><tbody>${o.scores.map((s) => `<tr><td>${esc(s.name)}</td><td>${fa(s.score)} از ${fa(s.points)}</td><td><small>${esc(s.why)}</small></td></tr>`).join('')}</tbody></table>
         <p class="sj-small">ترتیب درست کردن: ${o.fix_order.map(esc).join(' ← ')}</p>`) +
        box('فیلد نام (۳۰ حرف)', o.name_options.map((n) => `<div class="sj-out-row"><p>${esc(n.text)} <small class="${n.ok ? '' : 'sj-bad'}">${fa(n.chars)} حرف</small></p>${copy(n.text)}</div>`).join('')) +
        box('بایو (۱۵۰ حرف)', o.bio_options.map((n) => `<div class="sj-out-row"><p style="white-space:pre-line">${esc(n.text)} <small class="${n.ok ? '' : 'sj-bad'}">${fa(n.chars)} حرف</small></p>${copy(n.text)}</div>`).join('')) +
        box('سه پست پین', `<ol>${o.pinned_plan.map((p) => `<li>${esc(p)}</li>`).join('')}</ol>`) +
        box('هایلایت‌ها', `<p>${o.highlights.map(esc).join(' · ')}</p>`) +
        box('لینک و گرید', `<p>${esc(o.link_advice)}</p><p>${esc(o.grid_advice)}</p><p class="sj-small">${esc(o.rest_needs)}</p>`);
    },
    human(o) {
      return box('متن تمیز', `<div class="sj-out-row"><p style="white-space:pre-line">${esc(o.clean)}</p>${copy(o.clean)}</div>
        <p class="sj-small">${fa(o.report.invisible)} حرف نامرئی پاک شد، ${fa(o.report.halfspace)} نیم‌فاصله درست شد، ${fa(o.report.replaced.length)} کلیشه عوض شد${o.report.replaced.length ? ': ' + o.report.replaced.slice(0, 6).map((r) => `«${esc(r.find)}» ← «${esc(r.replace || 'حذف')}»`).join('، ') : ''}</p>
        ${o.rewrote ? `<p class="sj-small">بازنویسی شد: ${o.rewrote.map(esc).join('؛ ')}</p>` : ''}`) +
        box('پنل تشخیص', `<div class="sj-tools"><span>قبل: ${badge(o.before)}</span><span>بعد: ${badge(o.after)}</span></div>${checks(o.after)}
          <p class="sj-small">این پنج سنجه روی سرور خودت اجرا می‌شن و چیزی جایی فرستاده نمی‌شه. شبیه نشونه‌هایی‌ان که ابزارهای تشخیص متن ماشینی می‌گیرن، ولی خودشون اون ابزارها نیستن و قول «غیرقابل‌تشخیص» نمی‌دن.</p>`) + flags(o.report.flags);
    },
    comment(o) {
      return o.items.map((it) => box('پست ' + fa(it.post), `<p class="sj-small">${esc(it.post_text)}</p>${it.options.map((op, i) => `<div class="sj-out-row ${i === it.pick ? 'pick' : ''}"><div><small>[${fa(op.type)} · ${esc(op.type_name)}]${i === it.pick ? ' · پیشنهاد من' : ''}</small><p>${esc(op.text)}</p>${op.warnings.length ? `<small class="sj-bad">${op.warnings.map(esc).join('، ')}</small>` : ''}</div>${copy(op.text)}</div>`).join('')}<p class="sj-small">${esc(it.why)}</p>`)).join('');
    },
    reply(o) {
      const B = { keyword: 'کلمهٔ کلیدی', lead: 'مشتری احتمالی', substance: 'حرف حساب', question: 'سؤال', support: 'حمایت', noise: 'بی‌ارزش' };
      return `<p class="sj-small">${fa(o.total)} کامنت · ${Object.entries(o.counts).filter(([, n]) => n).map(([k, n]) => fa(n) + ' ' + B[k]).join('، ')}</p>` +
        Object.keys(B).filter((b) => o.counts[b]).map((b) => box(B[b] + ' (' + fa(o.counts[b]) + ')', o.items.filter((x) => x.bucket === b).map((x) => `<div class="sj-out-row"><div><small>${esc(x.comment)}</small>
          ${x.reply ? `<p>${esc(x.reply)}</p>` : '<p class="sj-small">جواب نده (جواب دادن بهش دیده‌شدن می‌ده)</p>'}${x.reel_worthy ? `<small class="sj-ok">این سؤال یه ریله، نه فقط یه جواب.</small> ${chain('reel', { idea: 'جواب به این سؤال تو کامنت‌ها: ' + x.comment, formula: 16 }, 'ریلش رو بنویس')}` : ''}</div>${x.reply ? copy(x.reply) : ''}</div>`).join(''))).join('');
    },
    dm(o) {
      return (o.no_trigger ? '<p class="sj-error">دلیلی برای پیام امروز نیست؛ بدون دلیل، پیامی نفرست.</p>' : '') + (o.advice ? `<p class="sj-small">${esc(o.advice)}</p>` : '') +
        [['message', 'پیام'], ['followup_4', '۴ روز بعد'], ['followup_10', '۱۰ روز بعد']].filter(([k]) => o[k]).map(([k, l]) => box(l + ' · ' + fa(o.chars[k]) + ' حرف', `<div class="sj-out-row"><p style="white-space:pre-line">${esc(o[k])}</p>${copy(o[k])}</div>`)).join('');
    },
    repurpose(o) {
      const N = { claims: 'ادعا', numbers: 'عدد', stories: 'داستان', mechanisms: 'سازوکار', mistakes: 'اشتباه', lines: 'جملهٔ نقل‌کردنی' };
      const F = { reel: 'ریل', carousel: 'کاروسل', story: 'استوری' };
      return box('پیدا شد · از ' + fa(o.words) + ' کلمه', `<p>${Object.entries(o.counts).map(([k, n]) => fa(n) + ' ' + N[k]).join('، ')}</p>${o.thin ? `<p class="sj-error">${esc(o.thin_note)}</p>` : ''}
        <details><summary>همهٔ تکه‌ها</summary>${Object.entries(o.found).map(([k, v]) => v.length ? `<h4>${N[k]}</h4><ul>${v.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '').join('')}</details>`) +
        box('هفته', `<table class="sj-table"><tbody>${o.week.map((w) => `<tr><td><b>${esc(w.day)}</b></td><td>${F[w.format]}</td><td>${w.formula ? '#' + fa(w.formula_id) + ' ' + esc(w.formula) : ''}</td><td>${esc(w.angle)}<br><small>${esc(w.extract)}</small>${w.clip_note ? `<br><small>کلیپ: ${esc(w.clip_note)}</small>` : ''}</td>
          <td>${w.format === 'reel' ? chain('reel', { idea: w.angle + '\n' + w.extract, formula: w.formula_id }, 'بنویسش') : w.format === 'carousel' ? chain('carousel', { idea: w.angle + '\n' + w.extract }, 'بنویسش') : ''}</td></tr>`).join('')}</tbody></table>${warns(o.warnings)}`);
    },
  };

  let lastCarousel = null;
  function render(agent, out, input) {
    $('studio-result').innerHTML = R[agent](out, input || {});
    if (agent === 'carousel') { lastCarousel = out; $('carousel-png').addEventListener('click', () => downloadSlides(out)); }
  }

  // carousel files: each slide drawn on a 1080×1350 canvas in Vazirmatn, right to left
  function wrap(ctx, text, maxW) {
    const out = [];
    String(text || '').split('\n').forEach((para) => {
      let line = '';
      para.split(' ').forEach((w) => {
        const t = line ? line + ' ' + w : w;
        if (ctx.measureText(t).width > maxW && line) { out.push(line); line = w; } else line = t;
      });
      out.push(line);
    });
    return out;
  }
  async function downloadSlides(o) {
    try { await document.fonts.load('800 80px Vazirmatn'); await document.fonts.load('400 40px Vazirmatn'); } catch (e) { /* system font */ }
    const W = 1080, H = 1350, pad = 120, toFa = (s) => String(s).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
    // Persian digits in Persian text, but not inside Latin names like GPT-4 or handles
    const faText = (s) => String(s || '').replace(/(?<![A-Za-z0-9@#_./:-])\d+(?:[.,]\d+)*(?![A-Za-z0-9_/:-])/g, (n) => toFa(n).replace(/,/g, '٬').replace(/\./g, '٫'));
    for (const s of o.slides) {
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const x = c.getContext('2d');
      const g = x.createLinearGradient(0, 0, W, H);
      if (s.role === 'cover' || s.role === 'cta') { g.addColorStop(0, '#0a84ff'); g.addColorStop(1, '#5856d6'); } else { g.addColorStop(0, '#f5f7fa'); g.addColorStop(1, '#dfe6f2'); }
      x.fillStyle = g; x.fillRect(0, 0, W, H);
      const dark = !(s.role === 'cover' || s.role === 'cta');
      x.fillStyle = dark ? '#1d1d1f' : '#ffffff';
      x.direction = 'rtl'; x.textAlign = 'right';
      const hs = s.role === 'cover' ? 92 : 68;
      x.font = `800 ${hs}px Vazirmatn, Tahoma, sans-serif`;
      let y = s.role === 'cover' ? 480 : 300;
      wrap(x, faText(s.headline), W - pad * 2).forEach((l) => { x.fillText(l, W - pad, y); y += hs * 1.35; });
      x.font = `400 ${s.role === 'cover' ? 46 : 42}px Vazirmatn, Tahoma, sans-serif`;
      x.fillStyle = dark ? '#3a3a3c' : 'rgba(255,255,255,.92)';
      y += 30;
      wrap(x, faText(s.body), W - pad * 2).forEach((l) => { x.fillText(l, W - pad, y); y += 66; });
      x.font = '600 32px Vazirmatn, Tahoma, sans-serif';
      x.fillStyle = dark ? '#86868b' : 'rgba(255,255,255,.8)';
      x.fillText(toFa(s.n + '/' + o.slides.length), W - pad, H - 90);
      if (o.handle) { x.textAlign = 'left'; x.direction = 'ltr'; x.fillText('@' + o.handle.replace(/^@/, ''), pad, H - 90); }
      const a = document.createElement('a');
      a.href = c.toDataURL('image/png'); a.download = `slide-${String(s.n).padStart(2, '0')}.png`;
      document.body.append(a); a.click(); a.remove();
      await new Promise((r) => setTimeout(r, 350));  // browsers drop rapid-fire downloads
    }
  }

  // ---------- events ----------
  root.addEventListener('click', async (e) => {
    const card = e.target.closest('.sj-agent');
    if (card) { open(card.dataset.agent); return; }
    const c = e.target.closest('.sj-copy');
    if (c) { try { await navigator.clipboard.writeText(c.dataset.copy); const t = c.textContent; c.textContent = 'کپی شد ✓'; setTimeout(() => { c.textContent = t; }, 1500); } catch (err) { /* no clipboard */ } return; }
    const b = e.target.closest('[data-board]');
    if (b && window.sjBoard) { const d = JSON.parse(b.dataset.board); b.disabled = true; try { await window.sjBoard.add(d); b.textContent = 'رفت تو بُرد ✓'; } catch (err) { b.textContent = 'نرفت'; b.disabled = false; } return; }
    const ch = e.target.closest('[data-chain]');
    if (ch) { open(ch.dataset.chain, JSON.parse(ch.dataset.prefill)); return; }
    const h = e.target.closest('[data-hist]');
    if (h) {
      const d = await api('GET', '/api/me/studio/history/' + h.dataset.hist);
      open(d.agent, d.input); render(d.agent, d.output, d.input);
    }
  });
  $('studio-run').addEventListener('click', runAgent);

  async function history() {
    try {
      const d = await api('GET', '/api/me/studio/history');
      $('studio-history').innerHTML = d.items.length ? d.items.slice(0, 12).map((h) => `<button type="button" class="sj-chip-btn" data-hist="${h.i}">${esc(A[h.agent] ? A[h.agent].icon + ' ' + A[h.agent].title : h.agent)} · ${esc(String(Object.values(h.input || {}).find((v) => typeof v === 'string' && v) || '').slice(0, 30))}</button>`).join('')
        : '<p class="sj-small">هنوز چیزی ننوشتی.</p>';
    } catch (e) { /* signed out */ }
  }
  async function show(param) {
    if (!meta) { try { meta = await api('GET', '/api/me/studio/meta'); } catch (e) { meta = { formulas: [] }; } }
    $('studio-agents').innerHTML = ORDER.map((k) => `<button type="button" class="sj-agent" data-agent="${k}"><span>${A[k].icon}</span><b>${A[k].title}</b><small>${A[k].desc}</small></button>`).join('');
    $('studio-voice').hidden = !!(meta.voice && (meta.voice.who || meta.voice.samples));
    history();
    if (param && A[param]) open(param); else $('studio-form-card').hidden = true;
  }
  window.addEventListener('sj:page', (e) => { if (e.detail.page === 'studio') show(e.detail.param); });
})();
