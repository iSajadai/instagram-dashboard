"""The numbers behind two research agents, computed rather than guessed:

- swipe(): reels found in the niche, ranked by the outlier multiple (views over that account's own
  median, not raw views), each hook named by formula and scored, and what separates the top third
  from the bottom (swipe.py in instagram-agent-skill).
- audit(): the page's own reels the same way: outlier multiple, hold at 3 seconds, sends and follows
  per reach, by formula, length and topic (the measuring half of ig-audit)."""
import re, statistics

from . import hooks
from .text import latin_digits, words


def num(v):
    try:
        return float(re.sub(r"[^\d.]", "", latin_digits(str(v)).replace(",", "").replace("٬", "")) or "x")
    except ValueError:
        return None


def read_rows(text):
    """Rows pasted as TSV or CSV (account, followers, median, views, hook), with or without a header."""
    rows = []
    for line in str(text or "").strip().splitlines():
        cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.split(","))]
        if len(cells) < 5 or (num(cells[3]) is None and cells[3] in ("views", "بازدید")):
            continue
        rows.append({"account": cells[0], "followers": num(cells[1]), "median": num(cells[2]), "views": num(cells[3]),
                     "hook": ",".join(cells[4:]).strip()})
    return rows


def _first_line(caption):
    return (caption or "").strip().split("\n")[0][:160]


def swipe(rows):
    out = []
    for r in rows:
        if not r.get("hook") or not r.get("views") or not r.get("median"):
            continue
        fid, fname = hooks.classify(r["hook"])
        s = hooks.score(r["hook"])
        out.append({**r, "multiple": round(r["views"] / r["median"], 1), "formula_id": fid, "formula": fname,
                    "hook_score": s["overall"], "hook_words": len(words(r["hook"]))})
    ranked = sorted(out, key=lambda r: -r["multiple"])
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:] if len(ranked) > third else []

    def counts(items):
        c = {}
        for r in items:
            if r["formula_id"]:
                c[r["formula_id"]] = c.get(r["formula_id"], 0) + 1
        return c
    ct, cb = counts(top), counts(bottom)
    over = sorted(({"formula_id": f, "formula": hooks.formula(f)["name"], "top": n, "bottom": cb.get(f, 0)} for f, n in ct.items()),
                  key=lambda x: (-(x["top"] - x["bottom"]), -x["top"]))

    def med(items, key):
        v = [r[key] for r in items if r.get(key) is not None]
        return round(statistics.median(v), 1) if v else None
    return {"n": len(ranked), "accounts": len({r["account"] for r in ranked}), "ranked": ranked,
            "outliers": [r for r in ranked if r["multiple"] >= 3], "over_index": over,
            "hook_words": {"top": med(top, "hook_words"), "bottom": med(bottom, "hook_words")},
            "hook_score": {"top": med(top, "hook_score"), "bottom": med(bottom, "hook_score")},
            "unclassified": [r for r in ranked if not r["formula_id"]],
            "confidence": "کافی برای یه ادعا" if len(ranked) >= 30 and len({r["account"] for r in ranked}) >= 5
            else "کم؛ فقط یه نشونه‌ست، نتیجه نیست"}


def length_bucket(sec):
    if sec is None:
        return None
    return "زیر ۱۵ ثانیه" if sec < 15 else "۱۵ تا ۳۰" if sec < 30 else "۳۰ تا ۶۰" if sec < 60 else "بیشتر از ۶۰"


def audit(reels, topics=None):
    """The page's reels with the numbers that mean something, ranked by outlier multiple."""
    tl = {t["id"]: t["label"] for t in (topics or [])}
    vs = [r["views"] for r in reels if r.get("views")]
    med = statistics.median(vs) if vs else None
    rows = []
    for r in reels:
        v, reach = r.get("views"), r.get("reach")
        hook = _first_line(r.get("caption"))
        fid, fname = hooks.classify(hook)
        rows.append({
            "url": r.get("url"), "published": r.get("published"), "hook": hook, "views": v,
            "multiple": round(v / med, 1) if v and med else None,
            "hold_3s": r.get("view_rate"), "avg_watch": r.get("avg_watch"),
            "sends_per_1k_reach": round((r.get("shares") or 0) / reach * 1000, 1) if reach else None,
            "follows_per_1k_reach": round(r["follows"] / reach * 1000, 1) if reach and r.get("follows") is not None else None,
            "saves_per_1k_reach": round((r.get("saves") or 0) / reach * 1000, 1) if reach else None,
            "length": length_bucket(r.get("duration")), "duration": r.get("duration"),
            "topic": tl.get(r.get("topic"), "سایر") if r.get("topic") else None,
            "formula_id": fid, "formula": fname, "hook_score": hooks.score(hook)["overall"] if hook else None,
        })
    ranked = sorted([x for x in rows if x["multiple"] is not None], key=lambda x: (-x["multiple"], -(x["sends_per_1k_reach"] or 0)))
    k = min(5, max(1, len(ranked) // 2))
    top, bottom = ranked[:k], ranked[-k:][::-1] if len(ranked) > k else []

    def mean(items, key):
        v = [x[key] for x in items if x.get(key) is not None]
        return round(statistics.mean(v), 1) if v else None

    def group(key):
        g = {}
        for x in ranked:
            if x.get(key):
                g.setdefault(x[key], []).append(x["multiple"])
        return sorted(({"group": a, "n": len(b), "mean_multiple": round(statistics.mean(b), 2)} for a, b in g.items()),
                      key=lambda x: -x["mean_multiple"])
    return {"n": len(ranked), "median_views": med, "top": top, "bottom": bottom,
            "compare": {key: {"top": mean(top, key), "bottom": mean(bottom, key)}
                        for key in ("hold_3s", "avg_watch", "sends_per_1k_reach", "follows_per_1k_reach", "hook_score", "duration")},
            "by_formula": group("formula"), "by_length": group("length"), "by_topic": group("topic"),
            "confidence": "کافی برای دیدن الگو" if len(ranked) >= 25 else f"فقط {len(ranked)} ریل؛ هر الگویی که دیده بشه هنوز حدسه"}
