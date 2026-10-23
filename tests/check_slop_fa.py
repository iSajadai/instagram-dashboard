#!/usr/bin/env python3
r"""check_slop_fa.py - validate slop_fa.json and run Persian sanity tests (stdlib only).

Matching rule for words/phrases (the detection panel uses the same one):
  1. normalise text: ARABIC YEH -> PERSIAN YEH, ARABIC KAF -> KEHEH
  2. pattern = (?<![؀-ۿ‌A-Za-z]) + re.escape(find) with every
     escaped space / ZWNJ replaced by [\s‌]+ + (?![؀-ۿ‌A-Za-z])
  Because a space and a ZWNJ compile to the same class, variant spellings such as
  "می‌باشد" / "می باشد" give the same pattern, so hits are counted once per span
  (longest entries claim their span first, as humanize.py replaces longest first).

Usage:  python3 check_slop_fa.py [path/to/slop_fa.json]
Exit code 0 when every check passes.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "sajadai", "fa", "data", "slop_fa.json")
ZWNJ = "‌"
GAP = r"[\s‌]+"  # written escaped so the ZWNJ replace in lex_pattern() cannot rewrite it
BS = chr(92)
def _u(n):
    return BS + 'u' + format(n, '04x')
# Boundary = Persian/Arabic LETTERS + ZWNJ + Latin. The literal range U+0600-U+06FF must NOT
# be used as the boundary: it contains the Persian comma, semicolon, question mark, percent
# and digits, so a word followed by a Persian comma would never match.
_R = [(0x0610, 0x061A), (0x0620, 0x065F), (0x066E, 0x06D3), (0x06D5, 0x06DC),
      (0x06DF, 0x06E8), (0x06EA, 0x06EF), (0x06FA, 0x06FF)]
BOUND = '[' + ''.join(_u(a) + '-' + _u(b) for a, b in _R) + _u(0x200c) + 'A-Za-z]'
LB = '(?<!' + BOUND + ')'
RB = '(?!' + BOUND + ')'
NAIVE_BOUND = '[' + _u(0x0600) + '-' + _u(0x06ff) + _u(0x200c) + 'A-Za-z]'

failures = []


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def normalize(text):
    return text.replace("ي", "ی").replace("ك", "ک")


def lex_pattern(find):
    esc = re.escape(find)
    # ZWNJ first, then escaped spaces: GAP itself contains a ZWNJ, so the
    # opposite order would rewrite the class it just inserted.
    esc = esc.replace(ZWNJ, "\x00").replace("\\ ", "\x00")
    esc = re.sub("\x00+", lambda m: GAP, esc)
    return re.compile(LB + esc + RB)


def lexicon_hits(text, lex):
    """Non-overlapping hits, longest find first. Returns list of (find, span)."""
    text = normalize(text)
    entries = sorted(lex["words"] + lex["phrases"], key=lambda e: len(e["find"]), reverse=True)
    taken, hits = [], []
    for e in entries:
        for m in lex_pattern(e["find"]).finditer(text):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            taken.append((a, b))
            hits.append((e["find"], m.group(0)))
    return hits


def structure_hits(text, lex):
    text = normalize(text)
    out = []
    for s in lex["structures"]:
        n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        if n:
            out.append((s["id"], n))
    return out


def marker_hits(text, patterns):
    text = normalize(text)
    return sum(len(re.compile(p, re.MULTILINE).findall(text)) for p in patterns)


def z(s):
    return s.replace("_", ZWNJ)


AI_TEXT = z("""در دنیای پرشتاب امروز، هوش مصنوعی نقش کلیدی ایفا می_کند. لازم به ذکر است که این فناوری نه تنها شیوه_ی کار ما را تغییر داده، بلکه سبک زندگی ما را نیز متحول کرده است. این فقط یک ابزار نیست، بلکه یک انقلاب واقعی است. همانطور که می_دانید، کسب_وکارها جهت بهینه_سازی فرآیندهای خود از ابزارهای قدرتمند و نوآورانه بهره_گیری می_نمایند. بیایید با هم نگاهی بیندازیم به چشم_انداز این اکوسیستم شگفت_انگیز.
نتیجه؟
تجربه_ای بی_نظیر، سریع و کاربردی. در نهایت می_توان گفت که آینده متعلق به کسانی می_باشد که امروز اقدام نمایند. امیدوارم این مطلب برای شما مفید بوده باشد.""")

HUMAN_TEXT = z("""دیروز سه ساعت با ChatGPT ور رفتم که یه پرامپت درست بنویسم، آخرش فهمیدم مشکل از خودم بود. هی می_گفتم «یه کپشن خوب بنویس» و انتظار داشتم ذهنم رو بخونه. بعد نشستم دقیق نوشتم پیجم درباره_ی چیه، مخاطبم کیه، چه لحنی دوست دارم، حتی دو تا از کپشن_های قدیمی خودم رو هم بهش دادم. جوابش اصلاً قابل مقایسه نبود. هنوزم بعضی جمله_هاش بوی ترجمه می_ده ولی دیگه لازم نیست از صفر بنویسم. شما هم اگه باهاش کار می_کنید، اول خودتون بدونید چی می_خواید، بعد ازش بخواید. راستش این یکی رو خودم نوشتم 😅""")


def wc(t):
    return len(re.findall(r"[؀-ۿ‌A-Za-z]+", t))


def main():
    lex = json.load(open(PATH, encoding="utf-8"))
    print(f"lexicon: {PATH}  (version {lex.get('version')})\n")

    print("STRUCTURE / SCHEMA")
    for key in ["version", "note", "invisible", "typographic", "words", "phrases", "structures",
                "colloquial_markers", "formal_markers", "pronouns", "number_words", "money_words", "time_units"]:
        ok(key in lex, f"key '{key}' present")
    zw = [e for e in lex["invisible"] if e["cp"] == "U+200C"]
    ok(len(zw) == 1 and zw[0]["action"] == "keep", "U+200C (ZWNJ) action is 'keep'")
    for cp, act in [("U+200B", "delete"), ("U+200D", "delete"), ("U+200E", "delete"), ("U+200F", "delete"),
                    ("U+202A-U+202E", "delete"), ("U+2066-U+2069", "delete"), ("U+E0000-U+E007F", "delete"),
                    ("U+00A0", "space"), ("U+202F", "space"), ("U+2009", "space")]:
        ok(any(e["cp"] == cp and e["action"] == act for e in lex["invisible"]), f"{cp} -> {act}")
    ok(all(e["action"] in ("keep", "delete", "space") for e in lex["invisible"]), "invisible actions valid")
    ok(all({"from", "name", "to", "signal"} <= set(e) for e in lex["typographic"]), "typographic entries have from/name/to/signal")
    ok(not any(ZWNJ in e["from"] for e in lex["typographic"]), "typographic never touches ZWNJ")

    entries = lex["words"] + lex["phrases"]
    finds = [e["find"] for e in entries]
    dups = sorted({f for f in finds if finds.count(f) > 1})
    ok(not dups, f"no duplicate 'find' values ({len(finds)} entries)" + (f" dups={dups}" if dups else ""))
    ok(all(isinstance(e.get("replace"), str) for e in entries), "every replacement is a string")
    ok(all(e["find"].strip() == e["find"] and e["find"] for e in entries), "no empty/padded finds")
    ok(not any(c in f for f in finds for c in "يك"), "no Arabic yeh/kaf inside finds (text is normalised)")
    ok(all(e.get("family") for e in entries), "every entry has a family")
    bad = []
    for e in entries:
        try:
            lex_pattern(e["find"])
        except re.error as ex:
            bad.append((e["find"], str(ex)))
    ok(not bad, "every word/phrase pattern compiles" + (f" {bad}" if bad else ""))
    for sec in ["colloquial_markers", "formal_markers", "pronouns"]:
        bad = []
        for p in lex[sec]:
            try:
                re.compile(p, re.MULTILINE)
            except re.error as ex:
                bad.append((p, str(ex)))
        ok(not bad, f"every {sec} regex compiles ({len(lex[sec])})" + (f" {bad}" if bad else ""))
    bad = []
    for s in lex["structures"]:
        try:
            re.compile(s["regex"], re.MULTILINE)
        except re.error as ex:
            bad.append((s["id"], str(ex)))
    ok(not bad, f"every structure regex compiles ({len(lex['structures'])})" + (f" {bad}" if bad else ""))
    ids = [s["id"] for s in lex["structures"]]
    ok(len(ids) == len(set(ids)), "structure ids unique")
    ok("\\b" not in "".join(s["regex"] for s in lex["structures"]), "no \\b in structure regexes")

    shared = {}
    for e in entries:
        shared.setdefault(lex_pattern(e["find"]).pattern, []).append(e["find"])
    same = sum(1 for v in shared.values() if len(v) > 1)
    print(f"  INFO  {same} pattern(s) shared by space/ZWNJ spelling variants (counted once per span)")

    print("\nSPELLING VARIANTS")
    for t in [z("این ابزار می_باشد."), "این ابزار می باشد.", "این ابزار میباشد.", "اين ابزار مي_باشد.".replace("_", ZWNJ)]:
        ok(len(lexicon_hits(t, lex)) == 1, f"'{t}' -> 1 hit")
    ok(len(lexicon_hits(z("بی_نظیرترین"), lex)) == 0, "no partial match inside a longer word (بی‌نظیرترین)")
    ok(len(lexicon_hits(z("تجربه_ای بی_نظیر، سریع"), lex)) == 1, "word followed by Persian comma matches (بی‌نظیر،)")
    ok(len(lexicon_hits(z("چرا جهت؟"), lex)) == 1, "word followed by Persian question mark matches (جهت؟)")
    naive = re.compile("(?<!" + NAIVE_BOUND + ")" + re.escape(z("بی_نظیر")) + "(?!" + NAIVE_BOUND + ")")
    print("  INFO  naive U+0600-U+06FF boundary on 'بی‌نظیر،' ->", "match" if naive.search(z("بی_نظیر،")) else "NO MATCH (why the letter-only boundary is used)")
    ok(lex.get("matching", {}).get("boundary_class") == BOUND, "JSON 'matching.boundary_class' equals checker boundary")
    ok(len(lexicon_hits(z("جهت_یابی"), lex)) == 0, "no match across ZWNJ-joined compound (جهت‌یابی)")

    print("\nTEST 1  formal AI-ish paragraph  (%d words)" % wc(AI_TEXT))
    h1 = lexicon_hits(AI_TEXT, lex)
    s1 = structure_hits(AI_TEXT, lex)
    print("        lexicon:", ", ".join(f for f, _ in h1))
    print("        structures:", s1)
    ok(wc(AI_TEXT) >= 80, "text >= 80 words")
    ok(len(h1) >= 6, f"lexicon hits >= 6 (got {len(h1)})")
    ok(len(s1) >= 2, f"structure hits >= 2 (got {len(s1)} kinds, {sum(n for _, n in s1)} total)")
    f1 = marker_hits(AI_TEXT, lex["formal_markers"])
    c1 = marker_hits(AI_TEXT, lex["colloquial_markers"])
    ok(f1 >= 4, f"formal_markers >= 4 (got {f1}; colloquial {c1})")

    print("\nTEST 2  natural colloquial caption  (%d words)" % wc(HUMAN_TEXT))
    h2 = lexicon_hits(HUMAN_TEXT, lex)
    s2 = structure_hits(HUMAN_TEXT, lex)
    print("        lexicon:", ", ".join(f for f, _ in h2) or "-")
    print("        structures:", s2 or "-")
    ok(wc(HUMAN_TEXT) >= 60, "text >= 60 words")
    ok(len(h2) <= 1, f"lexicon hits <= 1 (got {len(h2)})")
    ok(len(s2) == 0, f"structure hits == 0 (got {len(s2)})")
    c2 = marker_hits(HUMAN_TEXT, lex["colloquial_markers"])
    f2 = marker_hits(HUMAN_TEXT, lex["formal_markers"])
    ok(c2 >= 4, f"colloquial_markers >= 4 (got {c2}; formal {f2})")
    p1 = marker_hits(AI_TEXT, lex["pronouns"])
    p2 = marker_hits(HUMAN_TEXT, lex["pronouns"])
    ok(p2 / wc(HUMAN_TEXT) > p1 / wc(AI_TEXT), f"pronoun density higher in caption ({p2}/{wc(HUMAN_TEXT)}) than AI text ({p1}/{wc(AI_TEXT)})")

    print("\nTEST 3  Instagram structures fire on IG slop")
    ig = z("اسکرول نکن!!!\nتو این ویدیو می_خوام بهتون بگم چطور اکسپلور شی.\n✅ نکته اول\n✅ نکته دوم\n✅ نکته سوم\nفالو کن برای قسمت بعد\n#اینستاگرام #ریلز #محتوا #بازاریابی #پیج #فالوور")
    s3 = dict(structure_hits(ig, lex))
    for sid in ["stop-scroll", "in-this-video", "emoji-bullets", "follow-bait", "hashtag-wall", "bang-bang"]:
        ok(sid in s3, f"structure '{sid}' fires")
    ok(len(lexicon_hits(ig, lex)) >= 2, "IG lexicon hits >= 2")

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
