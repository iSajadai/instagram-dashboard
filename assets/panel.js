/* Helpers shared by the panel pages. Every call sends the X-Requested-With header the server
   requires on changes, so another site can't make them with the visitor's cookie. */
window.pn = {
  async api(method, path, body) {
    const res = await fetch(path, {
      method, credentials: 'same-origin',
      headers: { 'X-Requested-With': 'sajadai', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (res.status === 401 && !path.startsWith('/api/login')) { location.href = '/login'; throw new Error('signed out'); }
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'خطا (' + res.status + ')');
    return data;
  },
  // show a result next to the button that asked for it
  say(el, text, ok) { el.textContent = text || ''; el.className = 'pn-msg' + (text ? (ok ? ' ok' : ' bad') : ''); },
  async run(btn, msgEl, fn) {
    btn.disabled = true;
    try { const r = await fn(); pn.say(msgEl, (r && r.message) || 'ذخیره شد ✓', !(r && r.ok === false)); return r; }
    catch (e) { pn.say(msgEl, e.message, false); }
    finally { btn.disabled = false; }
  },
  el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v != null) e.setAttribute(k, v); });
    kids.flat().forEach((k) => e.append(k == null ? '' : k));
    return e;
  },
  when(ts) { return ts ? new Intl.DateTimeFormat('fa-IR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran' }).format(new Date(ts * 1000)) : '—'; },
  async copy(text, btn) {
    try { await navigator.clipboard.writeText(text); const t = btn.textContent; btn.textContent = 'کپی شد ✓'; setTimeout(() => { btn.textContent = t; }, 1500); }
    catch (e) { /* no clipboard: the text is on screen to copy by hand */ }
  },
};
