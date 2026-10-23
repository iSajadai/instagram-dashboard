"""The Jalali calendar and Iran's occasions against known official dates."""
import os, sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai import calendar_fa as c  # noqa: E402


def test_round_trip_over_years():
    d = date(2020, 1, 1)
    while d < date(2032, 1, 1):
        assert c.to_gregorian(*c.to_jalali(d)) == d, d
        d += timedelta(days=1)


def test_known_dates():
    assert c.to_gregorian(1405, 1, 1) == date(2026, 3, 21)  # Nowruz 1405
    assert c.to_jalali(date(2026, 10, 23)) == (1405, 8, 1)
    assert c.weekday(date(2026, 10, 24)) == 0  # a Saturday
    assert c.month_length(1403, 12) == 30 and c.month_length(1404, 12) == 29  # 1403 was a leap year


def titles(jy):
    return {(o["date"], o["title"]) for o in c.occasions_of(jy)}


def test_official_lunar_holidays_1404_1405():
    t = titles(1404)
    assert (c.to_gregorian(1404, 4, 15), "عاشورای حسینی") in t  # Ashura 1404 = 15 Tir
    assert (c.to_gregorian(1404, 1, 11), "عید فطر") in t
    t = titles(1405)
    assert (c.to_gregorian(1405, 1, 1), "عید فطر") in t  # Eid al-Fitr fell on Nowruz in 1405
    assert (c.to_gregorian(1405, 4, 4), "عاشورای حسینی") in t
    assert all(not o["approximate"] for o in c.occasions_of(1405))


def test_other_years_are_marked_approximate():
    assert any(o["approximate"] for o in c.occasions_of(1407) if o["kind"] == "lunar")
    assert all(not o["approximate"] for o in c.occasions_of(1407) if o["kind"] == "solar")


def test_month_page():
    m = c.month(1405, 8)
    assert m["title"] == "آبان ۱۴۰۵" and len(m["days"]) == 30 and m["days"][0]["date"] == "2026-10-23" and m["lead"] == 6


if __name__ == "__main__":
    bad = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", k, repr(e)[:300])
    sys.exit(1 if bad else 0)
