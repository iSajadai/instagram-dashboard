/* Small shared UI pieces, loaded before the page scripts: VibeFarsi's empty state, the theme toggle's
   sun/moon icon, and the section index for the long settings pages. */
(function () {
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /** Empty state: say what's missing, and offer the one action that fixes it (VibeFarsi EmptyState). */
  window.vfEmpty = (icon, title, desc, actionHtml) =>
    `<div class="vf-empty" role="status"><span class="vf-empty-ico"><svg aria-hidden="true"><use href="#${esc(icon || 'i-inbox')}"></use></svg></span>`
    + `<b>${esc(title)}</b>${desc ? `<p>${esc(desc)}</p>` : ''}${actionHtml || ''}</div>`;

  // the theme button shows what it switches to: a moon in light mode, a sun in dark
  const root = document.documentElement;
  const syncTheme = () => document.querySelectorAll('[data-theme-toggle] use').forEach((u) => u.setAttribute('href', root.getAttribute('data-theme') === 'dark' ? '#i-sun' : '#i-moon'));
  new MutationObserver(syncTheme).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  document.addEventListener('DOMContentLoaded', syncTheme);

  /** Section index for a long page: one link per card heading, the current one marked while scrolling. */
  window.vfToc = (main, nav, icons) => {
    const cards = [...main.querySelectorAll(':scope > section')];
    const draw = () => {
      nav.innerHTML = '<b>بخش‌ها</b>' + cards.filter((c) => !c.hidden && c.querySelector('h2')).map((c) => {
        if (!c.id) c.id = 'sec-' + Math.random().toString(36).slice(2, 7);
        const ic = (icons || {})[c.id] || 'i-settings';
        return `<a href="#${c.id}"><svg aria-hidden="true"><use href="#${ic}"></use></svg>${esc(c.querySelector('h2').textContent)}</a>`;
      }).join('');
    };
    draw();
    const mark = (id) => nav.querySelectorAll('a').forEach((a) => {
      const on = a.getAttribute('href') === '#' + id;
      a.toggleAttribute('aria-current', on);
      if (on) a.setAttribute('aria-current', 'true');
      // on phones the index is a horizontal row: move just the row (scrollIntoView would also stop the page's scroll)
      if (on && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2;  // instant: a second smooth scroll would cancel the page's
    });
    // the current section is the last one whose top has passed 30% of the window
    const current = () => {
      let cur = null;
      for (const c of cards) if (!c.hidden && c.getBoundingClientRect().top <= innerHeight * 0.3) cur = c;
      return cur || cards.find((c) => !c.hidden);
    };
    let ticking = false, locked = 0;
    addEventListener('scroll', () => {
      if (ticking || Date.now() < locked) return;
      ticking = true;
      requestAnimationFrame(() => { ticking = false; const c = current(); if (c) mark(c.id); });
    }, { passive: true });
    nav.addEventListener('click', (e) => {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      e.preventDefault();
      const id = a.getAttribute('href').slice(1);
      const target = document.getElementById(id);
      locked = Date.now() + 1200;  // the smooth scroll passes other sections; keep the clicked one marked
      // scroll-margin-top in ui.css leaves room for the sticky index on phones
      target.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      mark(id);
      history.replaceState(null, '', '#' + id);
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });  // keyboard and screen-reader users land in the section
    });
    requestAnimationFrame(() => { const c = location.hash && document.getElementById(location.hash.slice(1)); mark((c || current() || {}).id); });
    return () => { draw(); const c = current(); if (c) mark(c.id); };  // call again after cards show or hide
  };
})();
