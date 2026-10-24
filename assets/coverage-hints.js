/* Empty numbers on the dashboard point at the source that would fill them: «برای این عدد، X رو وصل کن»,
   linking to that source's card in Settings → اتصال‌ها. Panel only (needs /api/me/coverage). */
(function () {
  const CAP = { followers: 'followers_daily', views: 'views', view_rate: 'view_rate', save_rate: 'saves', shares_per_1k: 'shares',
    non_follower_share: 'follower_split', follows: 'follows', engaged: 'engaged' };
  const COLS = { watch_pct: 'duration', duration: 'duration', follows: 'follows', avg_watch: 'avg_watch', watch_total: 'watch_total', save_rate: 'saves' };
  let cov = null;
  const suggest = (cap) => {
    if (!cov) return null;
    for (const g of cov.groups) for (const i of g.items) if (i.id === cap && i.state === 'missing' && i.suggest.length) return i.suggest[0];
    return null;
  };
  function paint() {
    if (!cov) return;
    document.querySelectorAll('#kpis [data-source="kpis"]').forEach((t) => {
      const box = t.parentElement;
      box.querySelectorAll('.sj-cover-hint').forEach((x) => x.remove());
      const s = t.textContent.trim() === '—' && suggest(CAP[t.dataset.field]);
      if (s) {
        const a = document.createElement('a');
        a.className = 'sj-cover-hint'; a.href = '/settings#src-' + s.id;
        a.textContent = 'برای این عدد، ' + s.title + ' رو وصل کن';
        box.append(a);
      }
    });
    const heads = [...document.querySelectorAll('#reels-table thead th')].map((th) => th.dataset.field);
    document.querySelectorAll('#reels-table tbody tr').forEach((tr) => [...tr.children].forEach((td, i) => {
      const cap = COLS[heads[i]];
      if (cap && td.textContent.trim() === '—' && !td.title) { const s = suggest(cap); if (s) td.title = 'برای این عدد، ' + s.title + ' رو وصل کن'; }
    }));
  }
  fetch('/api/me/coverage', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).then((c) => { cov = c; paint(); }).catch(() => {});
  if (window.dash && dash.onData) dash.onData(() => setTimeout(paint, 0));
  window.addEventListener('sj:page', () => setTimeout(paint, 50));
})();
