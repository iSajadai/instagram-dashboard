"""Command line for the Persian tools, used by the Claude skills in skills/ (copied there as
skills/ig-fa-tools/fa_tools.py with this package next to it). Standard library only.

  fa_tools.py hooks hooks.txt | --hook "یه خط"         rank Persian hooks, 0-100, with the formula each uses
  fa_tools.py beats script.txt [--target 30] [--wpm 150]   timed beat sheet
  fa_tools.py caption caption.txt [--keywords "a,b"]     caption linter
  fa_tools.py human draft.txt [-o clean.txt] [--formal]  humanize, then score before and after
  fa_tools.py detect draft.txt [after.txt] [--formal]    score only
  fa_tools.py swipe captured.tsv [--out swipe.md]        rank reels by outlier multiple, name the formulas
  fa_tools.py formulas [--id N]                          the 26 Persian hook formulas
  fa_tools.py rubric                                     the 12-item Persian profile rubric
Add --json to any command for machine-readable output."""
import argparse, json, sys

from . import beats, caption, hooks, human, viral
from .text import data, fa_digits


def read(path):
    return sys.stdin.read() if path in (None, "-") else open(path, encoding="utf-8").read()


def bar(score, width=20):
    n = round(score / 100 * width)
    return "█" * n + "·" * (width - n)


def show_score(s, label):
    print(f"\n{label}: {fa_digits(round(s['overall']))} ({s['verdict_fa']})")
    for c in s["checks"]:
        print(f"  {c['name']:<16} {bar(c['score'])} {fa_digits(round(c['score'])):>4}  {c['detail']}")
    if s["verdict"] not in ("PASS", "STRONG"):
        print(f"  ضعیف‌ترین: {s['weakest_fa']}. اول اینو درست کن.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fa_tools.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("hooks"); p.add_argument("file", nargs="?"); p.add_argument("--hook"); p.add_argument("--wpm", type=int, default=hooks.WPM)
    p = sub.add_parser("beats"); p.add_argument("file", nargs="?"); p.add_argument("--target", type=float); p.add_argument("--wpm", type=int, default=beats.WPM)
    p = sub.add_parser("caption"); p.add_argument("file", nargs="?"); p.add_argument("--keywords", default="")
    p = sub.add_parser("human"); p.add_argument("file", nargs="?"); p.add_argument("-o", "--out"); p.add_argument("--formal", action="store_true")
    p = sub.add_parser("detect"); p.add_argument("file", nargs="?"); p.add_argument("after", nargs="?"); p.add_argument("--formal", action="store_true")
    p = sub.add_parser("swipe"); p.add_argument("file", nargs="?"); p.add_argument("--out")
    p = sub.add_parser("formulas"); p.add_argument("--id", type=int)
    sub.add_parser("rubric")
    for p in sub.choices.values():
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = None

    if a.cmd == "hooks":
        lines = [a.hook] if a.hook else [l.strip() for l in read(a.file).splitlines() if l.strip()]
        out = [dict(r, formula=hooks.classify(r["text"])) for r in hooks.rank(lines, a.wpm)]
        if not a.json:
            print("رتبه‌بندی هوک‌ها\n" + "=" * 60)
            for i, r in enumerate(out):
                fid, fname = r["formula"]
                print(f"{'->' if i == 0 else '  '} {fa_digits(round(r['overall'])):>4} {r['verdict_fa']:<6} {r['text']}")
                print(f"        ضعیف‌ترین: {r['weakest_fa']}" + (f" · فرمول #{fa_digits(fid)} {fname}" if fid else " · فرمول: ناشناخته"))
                for f in r["flags"]:
                    print(f"        مشکل جدی: {f}")
            if out and out[0]["overall"] < 50:
                print("\nبهترینش زیر ۵۰ـه: هنوز هوک نداری، و ویرایش درستش نمی‌کنه. از یه فرمول دیگه دوباره بنویس.")
    elif a.cmd == "beats":
        out = beats.analyse(read(a.file), a.wpm, a.target)
        if not a.json:
            print(f"زمان‌بندی صحنه‌ها · {fa_digits(out['words'])} کلمه · حدود {fa_digits(out['total'])} ثانیه با {fa_digits(out['wpm'])} کلمه در دقیقه"
                  + (f" · هدف {fa_digits(out['target'])} ثانیه" if out["target"] else "") + "\n" + "=" * 60)
            for b in out["beats"]:
                m, s = divmod(b["start"], 60)
                print(f"  {fa_digits(int(m))}:{fa_digits(f'{s:04.1f}')}  {fa_digits(b['secs']):>5}ث  {b.get('label', ''):<6} {b['text']}")
            print("-" * 60)
            for f in out["flags"]:
                print("  - " + f)
    elif a.cmd == "caption":
        out = caption.analyse(read(a.file), [k for k in a.keywords.replace("،", ",").split(",") if k.strip()])
        if not a.json:
            print("چیزی که فید نشون می‌ده\n+" + "-" * 50 + "+")
            for line in out["visible"].split("\n"):
                print("| " + line)
            print("+" + "-" * 38 + (" ... بیشتر +" if out["truncated"] else "-" * 12 + "+"))
            for c in out["checks"]:
                print(f"  {'✓' if c['status'] == 'PASS' else '!' if c['status'] == 'WARN' else '✗'} {c['check']}: {c['detail']}")
            print(f"\nنتیجه: {out['verdict_fa']}")
    elif a.cmd == "human":
        out = human.run(read(a.file), casual=not a.formal)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(out["clean"] + "\n")
        if not a.json:
            r = out["report"]
            print(f"{fa_digits(r['invisible'])} حرف نامرئی پاک شد، {fa_digits(r['halfspace'])} نیم‌فاصله درست شد، "
                  f"{fa_digits(r.get('digits', 0))} عدد فارسی شد، {fa_digits(len(r['replaced']))} کلیشه عوض شد")
            for x in r["replaced"]:
                print(f"  «{x['find']}» ← «{x['replace'] or 'حذف'}»")
            if r["flags"]:
                print("\nالگوهایی که باید دستی بازنویسی بشن:")
                for f in r["flags"]:
                    print(f"  - {f['name']}: {f['fix']}" + (f" («{f['example']}»)" if f["example"] else ""))
            show_score(out["before"], "قبل")
            show_score(out["after"], "بعد")
            if not a.out:
                print("\nمتن تمیز:\n" + out["clean"])
    elif a.cmd == "detect":
        out = {"before": human.detect(read(a.file), not a.formal)}
        if a.after:
            out["after"] = human.detect(read(a.after), not a.formal)
        if not a.json:
            for k, v in out.items():
                show_score(v, {"before": "متن", "after": "بعد"}[k])
            print("\nاین پنج سنجه محلی‌ان و چیزی جایی فرستاده نمی‌شه؛ شبیه نشونه‌های ابزارهای تشخیص‌ان ولی خود اون ابزارها نیستن.")
    elif a.cmd == "swipe":
        out = viral.swipe(viral.read_rows(read(a.file)))
        lines = [f"سوایپ · {fa_digits(out['n'])} ریل · {fa_digits(out['accounts'])} حساب · مبنا: میانهٔ خود هر حساب · اطمینان: {out['confidence']}", "",
                 "بالای ۳ برابر:"]
        for r in out["outliers"]:
            lines.append(f"  {fa_digits(r['multiple'])}×  هوک {fa_digits(round(r['hook_score']))}  "
                         + (f"#{fa_digits(r['formula_id'])} {r['formula']}" if r["formula_id"] else "بی‌نام") + f"  {r['account']}  «{r['hook']}»")
        lines += ["", "فرمول‌هایی که تو یک‌سوم بالا بیشترن:"]
        lines += [f"  #{fa_digits(o['formula_id'])} {o['formula']}: بالا {fa_digits(o['top'])}، پایین {fa_digits(o['bottom'])}" for o in out["over_index"]] or ["  هنوز هیچی"]
        lines += [f"  میانهٔ طول هوک: بالا {fa_digits(out['hook_words']['top'])} کلمه، پایین {fa_digits(out['hook_words']['bottom'])} کلمه", "",
                  f"بی‌نام ({fa_digits(len(out['unclassified']))}): دستی بخونشون؛ یا نویزن یا فرمولی که هنوز تو فهرست نیست."]
        lines += [f"  {r['account']}: «{r['hook']}»" for r in out["unclassified"]]
        text = "\n".join(lines)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(text + "\n")
        if not a.json:
            print(text)
    elif a.cmd == "formulas":
        out = [f for f in hooks.formulas() if not a.id or f["id"] == a.id]
        if not a.json:
            for f in out:
                print(f"#{fa_digits(f['id'])} {f['name']}\n  قالب: {f['template']}\n  مثال: {f['example']}\n  روی صفحه: {f['on_screen']}\n"
                      f"  به درد: {f['best_for']}\n  دام: {f['trap']}\n")
    elif a.cmd == "rubric":
        out = data("rubric_fa.json")
        if not a.json:
            for i in out["items"]:
                print(f"{i['name']} ({fa_digits(i['points'])} امتیاز)\n  نمرهٔ کامل: {i['full_marks']}\n  خرابی رایج: {i['common_fail']}\n")
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
