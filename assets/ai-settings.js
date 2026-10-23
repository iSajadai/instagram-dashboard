/* Settings → هوش مصنوعی: the user's own AI providers, tried in order. Pick a service (Gemini free with a
   Google account, OpenRouter, Groq, …, the user's own 9router or Ollama, or Claude/GPT with an API key),
   paste the key, and the panel finds the models, picks one and checks it answers before saving it.
   Called by settings.html with the /api/me answer: window.sjAiCard(me, reload). */
(function () {
  const $ = (id) => document.getElementById(id);
  let me = null, reload = null, chosen = null;
  const models = {};  // provider entry id → the models its test found

  function catalog() { return me.ai.providers; }

  function drawChain() {
    const list = $('ai-chain');
    const chain = me.ai.chain || [];
    $('ai-test-all').hidden = !chain.length;
    if (!chain.length) {
      list.replaceChildren(pn.el('li', { class: 'ai-empty' }, 'هنوز سرویسی وصل نکردی. ساده‌ترین راه رایگان: Gemini با حساب گوگلت (پایین).'));
      return;
    }
    list.replaceChildren(...chain.map((c, i) => {
      const dl = 'ai-dl-' + c.id;
      const model = pn.el('input', { dir: 'ltr', value: c.model, list: dl, 'aria-label': 'مدل ' + c.label });
      model.addEventListener('change', () => save(chain.map((x) => ({ id: x.id, model: x.id === c.id ? model.value.trim() : x.model })), 'مدل عوض شد ✓'));
      const up = pn.el('button', { type: 'button', class: 'ai-mini', 'aria-label': 'بالاتر', disabled: i === 0 ? '' : null }, '↑');
      const down = pn.el('button', { type: 'button', class: 'ai-mini', 'aria-label': 'پایین‌تر', disabled: i === chain.length - 1 ? '' : null }, '↓');
      const del = pn.el('button', { type: 'button', class: 'ai-mini', 'aria-label': 'حذف ' + c.label }, 'حذف');
      const order = (j) => { const ids = chain.map((x) => x.id); [ids[i], ids[j]] = [ids[j], ids[i]]; save(ids.map((id) => ({ id })), 'ترتیب ذخیره شد ✓'); };
      up.addEventListener('click', () => order(i - 1));
      down.addEventListener('click', () => order(i + 1));
      del.addEventListener('click', () => { if (confirm(c.label + ' حذف بشه؟')) save(chain.filter((x) => x.id !== c.id).map((x) => ({ id: x.id })), 'حذف شد'); });
      return pn.el('li', { class: 'ai-item', 'data-id': c.id },
        pn.el('span', { class: 'ai-rank', 'aria-hidden': 'true' }, String(i + 1)),
        pn.el('div', { class: 'ai-body' },
          pn.el('b', {}, c.label, i === 0 ? pn.el('small', { class: 'ai-tag' }, 'اول این') : ''),
          pn.el('div', { class: 'ai-meta', dir: 'ltr' }, [c.base_url, c.key].filter(Boolean).join(' · ')),
          pn.el('label', { class: 'ai-model' }, 'مدل', model, pn.el('datalist', { id: dl }, (models[c.id] || []).map((m) => pn.el('option', { value: m })))),
          pn.el('span', { class: 'pn-msg', 'data-msg': '' })),
        pn.el('div', { class: 'ai-actions' }, up, down, del));
    }));
  }

  async function save(items, message) {
    try {
      const r = await pn.api('POST', '/api/me/ai/chain', { items });
      me.ai.chain = r.chain;
      drawChain();
      pn.say($('ai-msg'), message, true);
    } catch (e) { pn.say($('ai-msg'), e.message, false); }
  }

  function drawPicks() {
    const box = $('ai-picks');
    const cat = catalog(), groups = me.ai.groups;
    box.replaceChildren(...Object.entries(groups).map(([g, title]) => pn.el('fieldset', { class: 'ai-group' },
      pn.el('legend', {}, title),
      pn.el('div', { class: 'ai-tiles' }, Object.entries(cat).filter(([, p]) => p.group === g).map(([k, p]) => {
        const b = pn.el('button', { type: 'button', class: 'ai-tile', 'aria-pressed': 'false', 'data-p': k }, p.label);
        b.addEventListener('click', () => pick(k));
        return b;
      })))));
  }

  function pick(k) {
    chosen = k;
    const p = catalog()[k];
    document.querySelectorAll('.ai-tile').forEach((t) => t.setAttribute('aria-pressed', String(t.dataset.p === k)));
    $('ai-form').hidden = false;
    $('ai-help').textContent = p.note || '';
    const link = $('ai-keylink');
    link.hidden = !p.key_url;
    if (p.key_url) { link.href = p.key_url; link.textContent = p.needs_url ? 'راهنمای راه‌اندازی ↗' : (p.group === 'free' ? 'گرفتن کلید رایگان ↗' : 'گرفتن کلید ↗'); }
    $('ai-url-l').hidden = !p.needs_url;
    $('ai-url').placeholder = p.url_hint || '';
    $('ai-key-label').textContent = p.key_optional ? 'کلید (اگه گذاشتی)' : 'کلید';
    $('ai-newkey').placeholder = p.key_hint || '';
    $('ai-newmodel').value = '';
    $('ai-newmodel').placeholder = p.default ? 'خالی بذار؛ پیش‌فرض ' + p.default : 'خالی بذار تا خودمون بهترین رو انتخاب کنیم';
    pn.say($('ai-add-msg'), '', true);
    (p.needs_url ? $('ai-url') : $('ai-newkey')).focus();
  }

  async function connect(btn) {
    if (!chosen) return;
    btn.disabled = true;
    pn.say($('ai-add-msg'), 'در حال آزمایش… (پیدا کردن مدل‌ها و یه سؤال کوتاه)', true);
    try {
      const r = await pn.api('POST', '/api/me/ai/connect', { provider: chosen, key: $('ai-newkey').value.trim(), base_url: $('ai-url').value.trim(), model: $('ai-newmodel').value.trim() });
      pn.say($('ai-add-msg'), r.message, r.ok);
      if (r.ok) {
        models[r.entry.id] = r.models || [];
        me.ai.chain = [...(me.ai.chain || []).filter((c) => c.id !== r.entry.id), r.entry];
        $('ai-newkey').value = '';
        drawChain();
        if (reload) reload();
      }
    } catch (e) { pn.say($('ai-add-msg'), e.message, false); }
    finally { btn.disabled = false; }
  }

  async function testAll(btn) {
    btn.disabled = true;
    pn.say($('ai-msg'), 'در حال آزمایش همه…', true);
    try {
      const r = await pn.api('POST', '/api/me/ai/test', {});
      r.results.forEach((x) => { const m = document.querySelector(`.ai-item[data-id="${x.id}"] [data-msg]`); if (m) pn.say(m, x.message, x.ok); });
      const good = r.results.filter((x) => x.ok).length;
      pn.say($('ai-msg'), good ? `${good} از ${r.results.length} سرویس جواب دادن` : 'هیچ‌کدوم جواب ندادن', good > 0);
    } catch (e) { pn.say($('ai-msg'), e.message, false); }
    finally { btn.disabled = false; }
  }

  let wired = false;
  window.sjAiCard = (data, again) => {
    me = data; reload = again;
    if (!$('ai-card') || !me.ai || !me.ai.providers) return;
    $('ai-panel-note').textContent = me.ai.panel_provider
      ? 'ادمین پنل یه سرویس مشترک (' + (catalog()[me.ai.panel_provider] || {}).label + ') گذاشته که بدون تنظیم کار می‌کنه؛ اگه سرویس خودت رو اضافه کنی، اول سرویس‌های خودت امتحان می‌شن.'
      : '';
    drawChain();
    if (!wired) {
      wired = true;
      drawPicks();
      $('ai-connect').addEventListener('click', (e) => connect(e.currentTarget));
      $('ai-test-all').addEventListener('click', (e) => testAll(e.currentTarget));
      $('ai-newkey').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); connect($('ai-connect')); } });
    }
  };
})();
