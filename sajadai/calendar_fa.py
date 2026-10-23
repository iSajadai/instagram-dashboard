"""The Jalali calendar and Iran's occasions, for the content calendar and the weekly planner.

Ported from VibeFarsi's calendar kit (lib/jalali, lib/hijri, lib/iran-holidays): solar occasions by
Jalali date; religious ones by lunar Hijri date, which Iran fixes by moon sighting, so official month
starts live in a table (checked day by day for 1404 and 1405) and dates outside it are computed with
the tabular calendar and marked approximate. A few dates creators plan around (یلدا، ولنتاین، بلک‌فرایدی)
are listed too, as non-holidays."""
import math
from datetime import date, timedelta

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]


# ---------- Jalali ----------

def to_jalali(d):
    """date → (jy, jm, jd)"""
    gy, gm, gd = d.year, d.month, d.day
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


def to_gregorian(jy, jm, jd):
    """(jy, jm, jd) → date"""
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd + (31 * (jm - 1) if jm < 7 else (jm - 7) * 30 + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    for gm, n in enumerate([31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], 1):
        if gd <= n:
            return date(gy, gm, gd)
        gd -= n
    raise ValueError("bad Jalali date")


def month_length(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return (to_gregorian(jy + 1, 1, 1) - to_gregorian(jy, 12, 1)).days


def weekday(d):
    """0 = شنبه … 6 = جمعه"""
    return (d.weekday() + 2) % 7


# ---------- lunar Hijri, as Iran announces it ----------

# First day of each Hijri month as a Jalali date, from Iran's official calendar (VibeFarsi hijri.ts).
IRAN_HIJRI_MONTH_STARTS = {
    (1446, 9): (1403, 12, 12), (1446, 10): (1404, 1, 11), (1446, 11): (1404, 2, 9), (1446, 12): (1404, 3, 7),
    (1447, 1): (1404, 4, 6), (1447, 2): (1404, 5, 4), (1447, 3): (1404, 6, 3), (1447, 4): (1404, 7, 2), (1447, 5): (1404, 8, 1),
    (1447, 6): (1404, 9, 1), (1447, 7): (1404, 10, 1), (1447, 8): (1404, 11, 1), (1447, 9): (1404, 11, 30), (1447, 10): (1405, 1, 1),
    (1447, 11): (1405, 1, 30), (1447, 12): (1405, 2, 28), (1448, 1): (1405, 3, 26), (1448, 2): (1405, 4, 25), (1448, 3): (1405, 5, 23),
    (1448, 4): (1405, 6, 22), (1448, 5): (1405, 7, 20), (1448, 6): (1405, 8, 20), (1448, 7): (1405, 9, 20), (1448, 8): (1405, 10, 20),
    (1448, 9): (1405, 11, 19), (1448, 10): (1405, 12, 19),
}
VERIFIED_JALALI_YEARS = (1404, 1405)
_STARTS = sorted(((hy, hm, to_gregorian(*j)) for (hy, hm), j in IRAN_HIJRI_MONTH_STARTS.items()), key=lambda s: s[2])
_EPOCH = date(1970, 1, 1)
_TAB_EPOCH = 1948440 - 2440588  # 1 Muharram 1 AH (civil reckoning) in days since 1970-01-01


def _tabular_to_day(hy, hm, hd):
    return _TAB_EPOCH + hd - 1 + math.ceil(29.5 * (hm - 1)) + (hy - 1) * 354 + (3 + 11 * hy) // 30


def from_hijri(hy, hm, hd):
    """(date, approximate)"""
    for i, (y, m, start) in enumerate(_STARTS):
        if (y, m) == (hy, hm):
            known = (_STARTS[i + 1][2] - start).days if i + 1 < len(_STARTS) else 29
            return start + timedelta(days=hd - 1), hd > known
    return _EPOCH + timedelta(days=_tabular_to_day(hy, hm, hd)), True


def hijri_month_length(hy, hm):
    for i, (y, m, start) in enumerate(_STARTS):
        if (y, m) == (hy, hm) and i + 1 < len(_STARTS):
            return (_STARTS[i + 1][2] - start).days
    ny, nm = (hy + 1, 1) if hm == 12 else (hy, hm + 1)
    return _tabular_to_day(ny, nm, 1) - _tabular_to_day(hy, hm, 1)


def hijri_year_of(d):
    n = (d - _EPOCH).days
    return (30 * (n - _TAB_EPOCH) + 10646) // 10631


# ---------- occasions ----------

SOLAR = [  # (jm, jd, title, official holiday)
    (1, 1, "نوروز", True), (1, 2, "نوروز", True), (1, 3, "نوروز", True), (1, 4, "نوروز", True), (1, 12, "روز جمهوری اسلامی", True),
    (1, 13, "روز طبیعت", True), (2, 12, "روز معلم", False), (3, 14, "رحلت امام خمینی", True), (3, 15, "قیام ۱۵ خرداد", True),
    (9, 16, "روز دانشجو", False), (9, 30, "شب یلدا", False), (11, 22, "پیروزی انقلاب اسلامی", True), (12, 29, "روز ملی شدن صنعت نفت", True),
    # dates creators plan content around
    (11, 25, "ولنتاین", False), (11, 29, "سپندارمذگان (روز عشق ایرانی)", False), (7, 1, "بازگشایی مدرسه‌ها و دانشگاه‌ها", False),
    (4, 9, "روز جهانی شبکه‌های اجتماعی", False),
]
LUNAR = [  # (hm, hd or "last", title, official holiday)
    (1, 9, "تاسوعای حسینی", True), (1, 10, "عاشورای حسینی", True), (2, 20, "اربعین حسینی", True),
    (2, 28, "رحلت پیامبر و شهادت امام حسن مجتبی", True), (2, "last", "شهادت امام رضا", True), (3, 8, "شهادت امام حسن عسکری", True),
    (3, 17, "میلاد پیامبر و امام جعفر صادق", True), (6, 3, "شهادت حضرت فاطمه", True), (6, 20, "روز زن و مادر", False),
    (7, 13, "ولادت امام علی و روز پدر", True), (7, 27, "مبعث", True), (8, 15, "نیمهٔ شعبان", True), (9, 1, "آغاز ماه رمضان", False),
    (9, 21, "شهادت امام علی", True), (10, 1, "عید فطر", True), (10, 2, "تعطیل به مناسبت عید فطر", True),
    (10, 25, "شهادت امام جعفر صادق", True), (11, 1, "روز دختر", False), (12, 10, "عید قربان", True), (12, 18, "عید غدیر", True),
]
_cache = {}


def occasions_of(jy):
    """Every occasion of a Jalali year: [{date, title, holiday, kind, approximate}], by date."""
    if jy in _cache:
        return _cache[jy]
    first, last = to_gregorian(jy, 1, 1), to_gregorian(jy, 12, month_length(jy, 12))
    out = [{"date": to_gregorian(jy, jm, jd), "title": t, "holiday": h, "kind": "solar", "approximate": False} for jm, jd, t, h in SOLAR]
    wed = last  # چهارشنبه‌سوری: the evening before the year's last Wednesday
    while weekday(wed) != 4:
        wed -= timedelta(days=1)
    out.append({"date": wed - timedelta(days=1), "title": "چهارشنبه‌سوری", "holiday": False, "kind": "solar", "approximate": False})
    # Black Friday: the last Friday of November
    for gy in {first.year, last.year}:
        bf = date(gy, 11, 30)
        while bf.weekday() != 4:
            bf -= timedelta(days=1)
        if first <= bf <= last:
            out.append({"date": bf, "title": "بلک‌فرایدی", "holiday": False, "kind": "solar", "approximate": False})
    for hy in range(hijri_year_of(first) - 1, hijri_year_of(last) + 2):
        for hm, rule, t, h in LUNAR:
            hd = hijri_month_length(hy, hm) if rule == "last" else rule
            d, approx = from_hijri(hy, hm, hd)
            if first <= d <= last:
                out.append({"date": d, "title": t, "holiday": h, "kind": "lunar", "approximate": approx or jy not in VERIFIED_JALALI_YEARS})
    out.sort(key=lambda o: (o["date"], not o["holiday"]))
    _cache[jy] = out
    return out


def occasions_between(start, end):
    years = {to_jalali(start)[0], to_jalali(end)[0]}
    return [o for jy in sorted(years) for o in occasions_of(jy) if start <= o["date"] <= end]


def jfmt(d, year=False):
    """«۲۳ مهر» or «۲۳ مهر ۱۴۰۵»"""
    jy, jm, jd = to_jalali(d)
    s = f"{jd} {MONTHS[jm - 1]}" + (f" {jy}" if year else "")
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def month(jy, jm):
    """A Jalali month for the calendar page: its days (Saturday-first padding) with occasions."""
    first = to_gregorian(jy, jm, 1)
    n = month_length(jy, jm)
    occ = {}
    for o in occasions_between(first, first + timedelta(days=n - 1)):
        occ.setdefault(o["date"], []).append(o)
    days = [{"date": (first + timedelta(days=i)).isoformat(), "jd": i + 1, "weekday": weekday(first + timedelta(days=i)),
             "occasions": [{k: v for k, v in o.items() if k != "date"} for o in occ.get(first + timedelta(days=i), [])]} for i in range(n)]
    return {"jy": jy, "jm": jm, "title": f"{MONTHS[jm - 1]} {jy}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
            "lead": weekday(first), "days": days}
