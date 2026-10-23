"""Taking the machine fingerprint out of Persian text, and scoring what's left: the Persian version of
humanize.py and detect.py from instagram-agent-skill, driven by data/slop_fa.json.

What changes for Persian: the half-space (ZWNJ) is part of correct spelling and is kept, and where a
plain space stands in for it («می خوام»، «ریل ها») it's put back. There are no English-style
contractions, so the "voice" signal is register: on a conversational page, written-register verbs
(«می‌باشد»، «می‌کند»، «را») read as translated or generated. Names have no capitals; Latin brand
names and «quoted» terms count instead."""
import re, statistics, unicodedata

from .text import (EMOJI_RE, LETTERS, LINK_RE, ZWNJ, concrete_markers, fa_digits, lex, normalize, phrase_re, pronoun_hits,
                   register, sentences, words)

LATIN_NUM = re.compile(r"(?<![A-Za-z0-9@#_./:\-])[0-9]+(?:[.,][0-9]+)*(?![A-Za-z0-9_/:\-]|\.[0-9])")
CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP", "FINGERPRINT", "VOICE"]
CHECK_FA = {"BURSTINESS": "تنوع طول جمله", "SPECIFICITY": "جزئیات مشخص", "SLOP": "کلیشه‌های ماشینی", "FINGERPRINT": "اثر انگشت تایپی",
            "VOICE": "لحن آدم"}
VERDICT_FA = {"PASS": "آدمی", "REVIEW": "بازبینی", "FLAGGED": "ماشینی"}
HALF_SPACE = [
    # «می خوام» / «نمی دونم» → «می‌خوام» / «نمی‌دونم»
    (re.compile(rf"(?<![{LETTERS}{ZWNJ}])(ن?می) +(?=[{LETTERS}]{{2,}})"), lambda m: m.group(1) + ZWNJ),
    # «ریل ها» / «بهتر ین» → «ریل‌ها» / «بهترین»-style suffixes
    (re.compile(rf"(?<=[{LETTERS}]{{2}}) +(ها|های|هایی|هام|هات|هاش|هامون|هاتون|هاشون|ترین|تر(?=[\s.،؟!]))(?![{LETTERS}])"),
     lambda m: ZWNJ + m.group(1)),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """value on 0-100, where `human` → 100 and `machine` → 0."""
    return 50.0 if human == machine else clamp((value - machine) / (human - machine) * 100)


def _invisible_actions():
    out = {}
    for e in lex()["invisible"]:
        cp = e["cp"].upper().replace("U+", "")
        if "-" in cp:
            a, b = (int(x.replace("U+", ""), 16) for x in cp.split("-"))
            for c in range(a, b + 1):
                out[chr(c)] = e["action"]
        else:
            out[chr(int(cp, 16))] = e["action"]
    return out


def _skip_links(text, fn):
    """Apply fn to the text but not inside links."""
    parts, last = [], 0
    for m in LINK_RE.finditer(text):
        parts.append(fn(text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(fn(text[last:]))
    return "".join(parts)


def halfspace_fixes(text):
    """[(as written, as it should be)] for the half-spaces a plain space is standing in for."""
    out = []
    t = normalize(text)
    for pattern, repl in HALF_SPACE:
        for m in pattern.finditer(t):
            a = re.search(rf"[{LETTERS}{ZWNJ}]*$", t[:m.start()]).group(0)  # the rest of the word on each side
            b = re.match(rf"[{LETTERS}{ZWNJ}]*", t[m.end():]).group(0)
            before = a + m.group(0) + b
            out.append((before.strip(), pattern.sub(repl, before).strip()))
    return out


def humanize(text):
    """(clean text, report). Fixes characters, typography, half-spaces and the stock vocabulary;
    structural tells are only flagged, since rewriting a sentence's shape needs judgement."""
    t = str(text or "")
    rep = {"invisible": 0, "typographic": [], "replaced": [], "halfspace": 0, "flags": []}
    acts = _invisible_actions()
    out = []
    for ch in t:
        act = acts.get(ch) or ("delete" if unicodedata.category(ch) == "Cf" and ch != ZWNJ else None)
        if act == "delete":
            rep["invisible"] += 1
        elif act == "space":
            out.append(" ")
        else:
            out.append(ch)
    t = "".join(out)
    # half-spaces: one at a time, none beside a space or at the ends of a word
    t = re.sub(f"{ZWNJ}+", ZWNJ, t)
    t = re.sub(rf"{ZWNJ}(?=[\s.،؛؟!,]|$)|(?<=[\s]){ZWNJ}|^{ZWNJ}", "", t, flags=re.M)
    for e in lex()["typographic"]:
        n = t.count(e["from"])
        if n:
            if e["from"] in "‘’" and e.get("to") == "'":
                t = t.replace(e["from"], "'")
            elif e["from"] in "“”":
                t = re.sub("“([^”\n]*)”", r"«\1»", t).replace("“", "«").replace("”", "»")
            else:
                t = t.replace(e["from"], e["to"])
            rep["typographic"].append({"name": e["name"], "count": n, "signal": e.get("signal", True)})
    # the em dash pass leaves «،،» or «، .» behind
    t = re.sub(r"\s*،\s*([،.؟!])", r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t)

    def fix_halfspaces(s):
        for pattern, repl in HALF_SPACE:
            s, n = pattern.subn(repl, s)
            rep["halfspace"] += n
        return s
    t = _skip_links(t, fix_halfspaces)

    def fa_numbers(s):
        # Latin digits in a Persian sentence become Persian; not inside Latin names («GPT-4»), handles, times or versions
        def one(m):
            rep["digits"] = rep.get("digits", 0) + 1
            return fa_digits(m.group(0)).replace(",", "٬").replace(".", "٫")  # Persian thousands and decimal separators
        return LATIN_NUM.sub(one, s)
    if len(re.findall(f"[{LETTERS}]", t)) > len(re.findall("[A-Za-z]", t)):
        t = _skip_links(t, fa_numbers)

    def swap(s):
        s = normalize(s)
        for e, p in slop_entries():
            s, n = p.subn(lambda m: e["replace"], s)
            if n:
                rep["replaced"].append({"find": e["find"], "replace": e["replace"], "count": n})
        return s
    t = _skip_links(t, swap)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" +([،.؟!؛])", r"\1", t)
    t = re.sub(r"(^|\n)[ \t]*[،,]\s*", r"\1", t)
    rep["flags"] = structure_flags(t)
    return t.strip(), rep


def structure_flags(text):
    t = normalize(text)
    out = []
    for s in lex()["structures"]:
        try:
            found = re.findall(s["regex"], t, re.M)
        except re.error:
            continue
        if found:
            m = re.search(s["regex"], t, re.M)
            out.append({"id": s["id"], "name": s["name"], "fix": s["fix"], "count": len(found),
                        "example": t[max(0, m.start()):m.end()][:80] if m else ""})
    return out


def slop_entries():
    """The lexicon, longest first, with spelling variants («می‌باشد»/«می باشد») that compile to the same
    pattern kept once."""
    seen, out = set(), []
    for e in sorted(lex()["phrases"] + lex()["words"], key=lambda e: -len(e["find"])):
        p = phrase_re(e["find"])
        if p.pattern not in seen:
            seen.add(p.pattern)
            out.append((e, p))
    return out


def slop_hits(text):
    """[(entry, count)]: non-overlapping, longest phrase first, so «لازم به ذکر است» isn't also counted as «است»-style hits."""
    t = normalize(text)
    taken, found = [], []
    for e, p in slop_entries():
        n = 0
        for m in p.finditer(t):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                taken.append((m.start(), m.end()))
                n += 1
        if n:
            found.append((e["find"], n))
    return found


# ---------- the five checks ----------

def check_burstiness(text):
    lens = [len(words(s)) for s in sentences(text)]
    if len(lens) < 4:
        return 50.0, "برای قضاوت کوتاهه"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    return scale(cv, 0.70, 0.22), f"تنوع {cv:.2f} در {len(lens)} جمله (۰٫۵۵ به بالا خوبه)"


def check_specificity(text):
    w = words(text)
    if len(w) < 25:
        return 50.0, "برای قضاوت کوتاهه"
    nums, names, quoted, spoken = concrete_markers(text)
    hits = len(nums) + len(names) + len(quoted) + len(spoken)
    density = hits * 100 / len(w)
    return scale(density, 6.0, 0.5), f"{hits} چیز مشخص، {density:.1f} در هر ۱۰۰ کلمه (۴ به بالا خوبه)"


def check_slop(text):
    w = words(text)
    if not w:
        return 50.0, "خالیه"
    found = slop_hits(text)
    hits = sum(n for _, n in found)
    density = hits * 100 / len(w)
    detail = f"{hits} کلیشه، {density:.1f} در هر ۱۰۰ کلمه"
    if found:
        detail += " (" + "، ".join(f for f, _ in found[:4]) + ("، ..." if len(found) > 4 else "") + ")"
    return scale(density, 0.0, 4.0), detail


def check_fingerprint(text):
    acts = _invisible_actions()
    invisible = sum(1 for c in text if (acts.get(c) == "delete") or (unicodedata.category(c) == "Cf" and c != ZWNJ and c not in acts))
    em = text.count("—")
    curly = sum(text.count(c) for c in "“”‘’")
    ellip = text.count("…")
    hard = sum(text.count(c) for c in "   ")
    total = invisible * 4 + em * 2 + curly + ellip + hard
    per1k = total * 1000 / max(len(text), 1)
    return scale(per1k, 0.0, 12.0), f"{invisible} حرف نامرئی، {em} خط تیرهٔ بلند، {curly} گیومهٔ انگلیسی، {ellip} سه‌نقطهٔ یکجا، {hard} فاصلهٔ سخت"


def check_voice(text, casual=True):
    """Person, register and the shapes models default to."""
    w = words(text)
    if len(w) < 25:
        return 50.0, "برای قضاوت کوتاهه"
    person = pronoun_hits(text) * 100 / len(w)
    col, form = register(text)
    flags = structure_flags(text)
    tells = sum(f["count"] for f in flags)
    reg = col / (col + form) if col + form else 0.5
    reg_score = scale(reg, 0.75, 0.15) if casual else 70.0
    bullets = [len(words(b)) for b in re.findall(r"(?m)^\s*(?:[-*•]|[0-9۰-۹]+[.)-])\s+(.+)$", text)]
    uniform = len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6
    score = scale(person, 6.0, 0.5) * 0.3 + reg_score * 0.4 + clamp(100 - tells * 22) * 0.3 - (12 if uniform else 0)
    detail = f"{person:.1f} ضمیر شخصی در هر ۱۰۰ کلمه، " + (f"لحن {round(reg * 100)}٪ محاوره ({col} محاوره، {form} رسمی)، " if casual else "") + f"{tells} الگوی ساختاری"
    if flags or uniform:
        detail += " [" + "، ".join([f["name"] for f in flags[:3]] + (["فهرست هم‌اندازه"] if uniform else [])) + "]"
    return clamp(score), detail


def detect(text, casual=True):
    r = {"BURSTINESS": check_burstiness(text), "SPECIFICITY": check_specificity(text), "SLOP": check_slop(text),
         "FINGERPRINT": check_fingerprint(text), "VOICE": check_voice(text, casual)}
    s = [r[c][0] for c in CHECKS]
    overall = statistics.mean(s) * 0.6 + min(s) * 0.4  # one strong signal is enough for a reader to notice
    verdict = "PASS" if overall >= 70 and min(s) >= 55 else ("REVIEW" if overall >= 50 else "FLAGGED")
    weakest = min(CHECKS, key=lambda c: r[c][0])
    return {"overall": round(overall, 1), "verdict": verdict, "verdict_fa": VERDICT_FA[verdict], "weakest": weakest,
            "weakest_fa": CHECK_FA[weakest],
            "checks": [{"id": c, "name": CHECK_FA[c], "score": round(r[c][0], 1), "detail": r[c][1]} for c in CHECKS]}


def run(text, casual=True):
    """Clean it, then score before and after: what the panel shows for «آدمی‌کن»."""
    clean, report = humanize(text)
    return {"clean": clean, "report": report, "before": detect(text, casual), "after": detect(clean, casual),
            "emoji": len(EMOJI_RE.findall(clean))}
