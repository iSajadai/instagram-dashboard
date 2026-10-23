/* Settings → حالت آژانس: the client's report with the agency's name and colour, its public link, and the
   monthly send to the client's Telegram or email. */
(function () {
  const $ = (id) => document.getElementById(id);
  if (!$('agency-card')) return;
  let s = null;
  function show() {
    $('ag_name').value = s.name; $('ag_client').value = s.client; $('ag_color').value = s.color || '#0062d6';
    $('ag_days').value = String(s.days); $('ag_chat').value = s.chat; $('ag_email').value = s.email; $('ag_auto').checked = s.auto;
    $('ag-link-row').hidden = !s.link;
    if (s.link) { $('ag-url').textContent = s.link; $('ag-open').href = s.link; }
    $('ag-link-off').hidden = !s.link;
    const notes = [];
    if (!s.telegram_ready) notes.push('ربات تلگرام پنل تنظیم نشده؛ فرستادن به تلگرام کار نمی‌کنه تا ادمین تنظیمش کنه.');
    if (!s.smtp_ready) notes.push('ایمیل پنل (SMTP) تنظیم نشده؛ فرستادن ایمیل کار نمی‌کنه تا ادمین تنظیمش کنه.');
    if (s.sent) notes.push('آخرین ارسال خودکار: ماه ' + s.sent.replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]));
    $('ag-note').textContent = notes.join(' ');
  }
  async function load() {
    try { s = await pn.api('GET', '/api/me/agency'); show(); } catch (e) { /* not the owner */ }
  }
  const vals = () => ({ name: $('ag_name').value.trim(), client: $('ag_client').value.trim(), color: $('ag_color').value, days: Number($('ag_days').value),
    chat: $('ag_chat').value.trim(), email: $('ag_email').value.trim(), auto: $('ag_auto').checked, link: true });
  $('ag-save').addEventListener('click', (e) => pn.run(e.currentTarget, $('ag-msg'), async () => { const r = await pn.api('POST', '/api/me/agency', vals()); await load(); return { ok: true, message: r.link ? 'ذخیره شد ✓ لینک گزارش آماده‌ست.' : 'ذخیره شد' }; }));
  $('ag-link').addEventListener('click', (e) => pn.run(e.currentTarget, $('ag-msg'), async () => {
    if (s.link && !confirm('لینک قبلی دیگه کار نمی‌کنه. ادامه بدیم؟')) return { ok: true, message: '' };
    await pn.api('POST', '/api/me/agency/link', {}); await load(); return { ok: true, message: 'لینک تازه ساخته شد' };
  }));
  $('ag-link-off').addEventListener('click', (e) => pn.run(e.currentTarget, $('ag-msg'), async () => { await pn.api('POST', '/api/me/agency/link', { off: true }); await load(); return { ok: true, message: 'لینک خاموش شد' }; }));
  $('ag-send').addEventListener('click', (e) => pn.run(e.currentTarget, $('ag-msg'), async () => {
    await pn.api('POST', '/api/me/agency', vals());
    const r = await pn.api('POST', '/api/me/agency/send', {}); await load(); return r;
  }));
  load();
})();
