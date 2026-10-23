"""Pages the server draws itself, from one user's data.json: the public media kit (/kit/<slug>, for
brands; on only when the user turns it on) and the printable report (/report, signed in). Plain HTML
with Persian digits and Jalali dates, so they print and share without the dashboard's scripts."""
from datetime import datetime, timedelta
from html import escape
from statistics import median

from . import analysis, config

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x, digits=0, suffix=""):
    if x is None:
        return "—"
    s = f"{x:,.{digits}f}" if digits else f"{round(x):,}"
    return s.replace(",", "٬").replace(".", "٫").translate(FA) + suffix


def jalali(gy, gm, gd):
    """Gregorian date to Jalali (y, m, d)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def jdate(iso, year=True):
    try:
        y, m, d = jalali(int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    except (TypeError, ValueError):
        return "—"
    return (f"{d} {MONTHS[m - 1]} {y}" if year else f"{d} {MONTHS[m - 1]}").translate(FA)


def first_line(caption, n=70):
    line = (caption or "").strip().split("\n")[0]
    return line[:n] + ("…" if len(line) > n else "")


def period(d, start, end):
    """Reel and account numbers for days start..end (inclusive, Tehran dates)."""
    reels, _ = analysis.scored(d)
    inr = [r for r in reels if start <= analysis._day(r["published"]) <= end]
    views = sum(r["views"] or 0 for r in inr)
    reach = sum(r["reach"] or 0 for r in inr)
    vr = [r["view_rate_3s_pct"] for r in inr if r["view_rate_3s_pct"] is not None]
    vs = [r["views"] for r in inr if r["views"] is not None]
    fols = [a for a in d.get("account", []) if a.get("followers") is not None and a["day"] <= end]
    before = [a for a in fols if a["day"] < start]
    net = fols[-1]["followers"] - before[-1]["followers"] if fols and before else None
    return {"reels": inr, "n": len(inr), "views": views, "median": median(vs) if vs else None, "view_rate": sum(vr) / len(vr) if vr else None,
            "save_rate": sum(r["saves"] or 0 for r in inr) / views * 100 if views else None,
            "shares_1k": sum(r["shares"] or 0 for r in inr) / reach * 1000 if reach else None,
            "followers": fols[-1]["followers"] if fols else None, "followers_net": net}


def today():
    return datetime.now(analysis.TEH).date()


def tile(label, value, note=""):
    return f'<div class="tile"><div class="lbl">{escape(label)}</div><div class="num">{value}</div>{f"<div class=note>{note}</div>" if note else ""}</div>'


def change(cur, prev):
    if cur is None or prev in (None, 0):
        return ""
    p = (cur - prev) / prev * 100
    cls = "up" if p >= 0 else "down"
    return f'<span class="{cls}">{"▲" if p >= 0 else "▼"} {fa(abs(p))}٪ نسبت به دورهٔ قبل</span>'


def reel_rows(reels, link=True):
    rows = []
    for r in reels:
        name = escape(first_line(r.get("caption")) or "ریل")
        url = r.get("url") or ""
        title = f'<a href="{escape(url)}" target="_blank" rel="noopener">{name}</a>' if link and url.startswith("https://") else name
        rows.append(f'<tr><td>{title}</td><td>{jdate(analysis._day(r.get("published")), False)}</td><td>{fa(r.get("views"))}</td>'
                    f'<td>{fa(r.get("multiple_of_median"), 1, "×")}</td><td>{fa(r.get("view_rate_3s_pct"), 1, "٪")}</td></tr>')
    return ('<table><thead><tr><th>ریل</th><th>تاریخ</th><th>بازدید</th><th>چند برابر میانه</th><th>ماندن ۳ ثانیه</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>") if rows else '<p class="muted">ریلی تو این بازه نیست.</p>'


def audience(d):
    out = []
    countries = sorted(d.get("countries", []), key=lambda c: c.get("value") or c.get("followers") or 0, reverse=True)[:5]
    if countries:
        tot = sum(c.get("value") or c.get("followers") or 0 for c in d.get("countries", [])) or 1
        out.append("<h3>کشورها</h3><ul class='bars'>" + "".join(
            f"<li><span>{escape(str(c.get('country') or c.get('name') or c.get('key') or '?'))}</span>"
            f"<i style='width:{round((c.get('value') or c.get('followers') or 0) / tot * 100)}%'></i>"
            f"<b>{fa((c.get('value') or c.get('followers') or 0) / tot * 100)}٪</b></li>" for c in countries) + "</ul>")
    return "".join(out)


def template(name):
    return (config.ROOT / "panel" / name).read_text(encoding="utf-8")


def kit(d, prefs, username):
    """The public media kit: the page's reach and how its reels do, for a brand deciding on a collab."""
    t = today()
    cur = period(d, (t - timedelta(days=29)).isoformat(), t.isoformat())
    best = sorted([r for r in analysis.scored(d)[0] if analysis._day(r["published"]) >= (t - timedelta(days=89)).isoformat() and r["views"] is not None],
                  key=lambda r: r["views"], reverse=True)[:3]
    name = prefs.get("page_name") or username
    handle = f'<p class="handle" dir="ltr">@{escape(prefs["kit_handle"])}</p>' if prefs.get("kit_handle") else ""
    aud = audience(d)
    contact = (prefs.get("kit_contact") or "").strip()
    if contact.startswith(("https://", "http://")):
        cta = f'<a class="cta" href="{escape(contact)}" target="_blank" rel="noopener">همکاری با {escape(name)}</a>'
    elif "@" in contact and " " not in contact:
        cta = f'<a class="cta" href="mailto:{escape(contact)}">همکاری: {escape(contact)}</a>'
    else:
        cta = f'<p class="cta-text">{escape(contact)}</p>' if contact else ""
    body = f"""
      <header class="hero">
        <div class="avatar">{escape(name[:2].upper())}</div>
        <div><h1>{escape(name)}</h1>{handle}
          <p class="bio">{escape(prefs.get("kit_bio") or "")}</p></div>
      </header>
      <section class="tiles">
        {tile("فالوئر", fa(cur["followers"]))}
        {tile("بازدید ریل‌ها در ۳۰ روز", fa(cur["views"]))}
        {tile("میانهٔ بازدید هر ریل", fa(cur["median"]))}
        {tile("ریل در ۳۰ روز", fa(cur["n"]))}
        {tile("ماندن بعد از ۳ ثانیه", fa(cur["view_rate"], 1, "٪"), "درصد بیننده‌هایی که از ثانیهٔ ۳ رد شدن")}
        {tile("نرخ ذخیره", fa(cur["save_rate"], 1, "٪"))}
      </section>
      <section><h2>بهترین ریل‌های ۹۰ روز اخیر</h2>{reel_rows(best)}</section>
      {f"<section><h2>مخاطب‌ها</h2>{aud}</section>" if aud else ""}
      {f'<section class="contact">{cta}</section>' if cta else ""}
      <footer>آخرین به‌روزرسانی: {jdate(analysis._day(d.get("generated_at")) or t.isoformat())} · عددها مستقیم از آمار اینستاگرام</footer>"""
    return template("kit.html").replace("__TITLE__", escape(f"مدیاکیت {name}")).replace("<!--BODY-->", body)


def report(d, prefs, username, days=7, brand=None, public=False):
    """The printable report for the last `days` days against the `days` before them. brand: an agency's
    {"agency", "color", "client"} for a client's copy; public: opened from the client's link (no sign-in)."""
    t = today()
    start, end = t - timedelta(days=days - 1), t
    cur = period(d, start.isoformat(), end.isoformat())
    prev = period(d, (start - timedelta(days=days)).isoformat(), (start - timedelta(days=1)).isoformat())
    ranked = sorted([r for r in cur["reels"] if r["views"] is not None], key=lambda r: r["views"], reverse=True)
    goals = analysis.goals(d)
    goal_html = "".join(f"<li><b>{escape(g['label'] or '')}</b>: {fa(g['current'])} از {fa(g['target'])}"
                        + (" · " + fa(g["percent"]) + "٪" if g["percent"] is not None else "")
                        + f"<i class='bar'><i style='width:{g['percent'] or 0}%'></i></i></li>" for g in goals)
    times = analysis.best_times(d, 3)
    ideas = sorted(d.get("ideas", []), key=lambda i: i.get("priority") or 99)[:4]
    ins = d.get("insights", [])[:3]
    name = prefs.get("page_name") or username
    times_html = "".join(f"<li>{escape(x['day'])} ساعت {x['hour_tehran'].translate(FA)}</li>" for x in times)
    ins_html = "".join(f"<li>{escape(i.get('action') or i.get('title') or '')}</li>" for i in ins)
    ideas_html = "".join(f"<li><b>{escape(i.get('title') or '')}</b> — {escape(i.get('hook') or '')}</li>" for i in ideas)
    name = (brand or {}).get("client") or name
    brand_html = (f"<style>:root{{--accent:{brand['color']};--brand:{brand['color']}}} .rep-head{{border-top:6px solid var(--brand);padding-top:16px}}</style>"
                  f"<p class='brand-line'>{escape(brand['agency'])}</p>") if brand else ""
    body = f"""{brand_html}
      <header class="rep-head">
        <div><h1>گزارش {"هفتگی" if days == 7 else f"{fa(days)} روزه"} {escape(name)}</h1>
          <p class="muted">{jdate(start.isoformat())} تا {jdate(end.isoformat())}، در مقایسه با {fa(days)} روز قبلش</p></div>
        <button class="no-print" onclick="window.print()">چاپ یا ذخیرهٔ PDF</button>
      </header>
      <section class="tiles">
        {tile("فالوئر", fa(cur["followers"]), ("خالص " + fa(cur["followers_net"]) if cur["followers_net"] is not None else ""))}
        {tile("بازدید ریل‌ها", fa(cur["views"]), change(cur["views"], prev["views"]))}
        {tile("ریل منتشرشده", fa(cur["n"]), change(cur["n"], prev["n"]))}
        {tile("ماندن بعد از ۳ ثانیه", fa(cur["view_rate"], 1, "٪"), change(cur["view_rate"], prev["view_rate"]))}
        {tile("نرخ ذخیره", fa(cur["save_rate"], 1, "٪"), change(cur["save_rate"], prev["save_rate"]))}
        {tile("اشتراک در هر ۱۰۰۰ نفر", fa(cur["shares_1k"], 1), change(cur["shares_1k"], prev["shares_1k"]))}
      </section>
      <section><h2>ریل‌های این دوره</h2>{reel_rows(ranked[:8])}</section>
      {f'<section><h2>هدف‌ها</h2><ul class="goals">{goal_html}</ul></section>' if goals else ""}
      <section class="two">
        {f'<div><h2>بهترین ساعت انتشار</h2><ul>{times_html}</ul></div>' if times else ""}
        {f'<div><h2>نکته‌های تحلیل</h2><ul>{ins_html}</ul></div>' if ins else ""}
      </section>
      {f'<section><h2>ایده‌های هفتهٔ بعد</h2><ol>{ideas_html}</ol></section>' if ideas else ""}
      <footer>{("تهیه‌شده توسط " + escape(brand["agency"])) if brand else "ساخته‌شده با داشبورد اینستاگرام"} · {jdate(t.isoformat())}</footer>"""
    return template("report.html").replace("__TITLE__", escape(f"گزارش {name}")).replace("<!--BODY-->", body)
