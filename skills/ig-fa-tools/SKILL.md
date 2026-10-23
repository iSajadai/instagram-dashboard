---
name: ig-fa-tools
description: >-
  The Persian (Farsi) Instagram writing tools that the ig-*-fa skills run: score Persian Reel hooks
  out of 100 against 26 Persian formulas, time a Persian script beat by beat, lint a Persian caption
  (the 125 characters before «... more», hashtags, asks, half-spaces), humanize Persian text and score
  it on five checks, and rank viral reels by outlier multiple. Use when checking any Persian hook,
  script, caption, comment or DM, or when the user asks «این هوک خوبه؟»، «کپشنمو چک کن»،
  «این متن ماشینی به نظر میاد؟»، «نیم‌فاصله‌هاشو درست کن».
---

# ig-fa-tools

ابزارهای فارسی که بقیهٔ مهارت‌های `ig-*-fa` اجراشون می‌کنن. فقط کتابخونهٔ استاندارد پایتون، بدون اینترنت، چیزی جایی فرستاده نمی‌شه.

```bash
T=~/.claude/skills/ig-fa-tools/fa_tools.py
python3 $T hooks hooks.txt                 # رتبهٔ هوک‌ها (هر خط یکی)، ۰ تا ۱۰۰، با اسم فرمول
python3 $T hooks --hook "یه خط"            # امتیاز یه هوک
python3 $T beats script.txt --target 30    # زمان‌بندی صحنه‌ها (پیش‌فرض ۱۵۰ کلمه در دقیقه؛ --wpm)
python3 $T caption caption.txt --keywords "پرامپت,هوش مصنوعی"
python3 $T human draft.txt -o clean.txt    # آدمی‌کن: پاک‌سازی + امتیاز قبل و بعد (--formal برای متن رسمی)
python3 $T detect draft.txt clean.txt      # فقط امتیاز
python3 $T swipe captured.tsv --out ~/.claude/instagram/swipe.md
python3 $T formulas [--id 3]               # ۲۶ فرمول هوک فارسی
python3 $T rubric                          # چک‌لیست ۱۲ بخشی پروفایل
```

هر دستور با `--json` خروجی ماشینی می‌ده.

## چرا نسخهٔ فارسی جداست

- **نیم‌فاصله** (U+200C) بخشی از املای درسته («می‌خوام»، «ریل‌ها»). آدمی‌کن نگهش می‌داره و جاهایی که با فاصله نوشته شده («می خوام») درستش می‌کنه؛ نسخهٔ انگلیسی همه‌شون رو پاک می‌کرد.
- **نفی تو فارسی پیشوند فعله** («نکن»، «نمی‌شه»)، پس «چیزی در خطره» از روی فعل منفی هم شناخته می‌شه.
- **اسم خاص حرف بزرگ نداره**؛ اسم‌های لاتین (ChatGPT) و «عبارت‌های داخل گیومه» جای اون حساب می‌شن.
- **لحن آدم** تو فارسی با محاوره در برابر رسمی سنجیده می‌شه («می‌کنه» در برابر «می‌کند»، «را»، «می‌باشد»)، نه با contraction.
- عددهای لاتین تو جملهٔ فارسی فارسی می‌شن («۱۸٬۰۰۰»، «۲٫۵»)، ولی تو «GPT-4»، لینک و آیدی دست نمی‌خورن.

این پنج سنجه محلی‌ان و شبیه نشونه‌هایی‌ان که ابزارهای تشخیص متن ماشینی می‌گیرن؛ خود اون ابزارها نیستن و قول «غیرقابل‌تشخیص» نمی‌دن.

بومی‌شده از instagram-agent-skill (MIT، Jake Schincariol). کد اصلی این ابزارها تو `sajadai/fa` همین مخزنه؛ این پوشه با `python -m sajadai build-skills` ساخته می‌شه.
