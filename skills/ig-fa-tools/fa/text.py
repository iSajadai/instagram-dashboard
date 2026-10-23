"""Persian text basics shared by the tools: normalizing, splitting into words and sentences, and the
markers they all count (numbers, names, money). Python's \\b doesn't work in Persian, because the
half-space (ZWNJ, U+200C) inside «می‌خوام» isn't a word character, so boundaries here are explicit."""
import json, re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("data")
ZWNJ = "‌"
# Persian/Arabic letters, without the punctuation that lives in the same block (، ؛ ؟ ٪ ٫ ٬ ۔)
LETTERS = "ؐ-ؚؠ-ٟٮ-ۓە-ۜ۟-۪ۨ-ۯۺ-ۿ"  # no digits, no ، ؛ ؟ ٪
FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
DIGIT = "0-9۰-۹٠-٩"
WORD_RE = re.compile(rf"[A-Za-z{DIGIT}{LETTERS}$%٪{ZWNJ}][A-Za-z{DIGIT}{LETTERS}$%٪{ZWNJ}'’.,٫٬-]*")
SENT_RE = re.compile(r"[^.!?؟\n]+[.!?؟]*")
NUMBER_RE = re.compile(rf"[$]?[{DIGIT}][{DIGIT},٬٫.]*\s?(?:%|٪|k|K)?")
LATIN_NAME_RE = re.compile(r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9+.#-]{1,}")  # in Persian text a Latin word is nearly always a name or brand
QUOTED_RE = re.compile(r"«[^»\n]{1,40}»")
HASHTAG_RE = re.compile(rf"(?:^|(?<=\s))#[A-Za-z0-9_{DIGIT}{LETTERS}{ZWNJ}]+")
MENTION_RE = re.compile(r"(?:^|(?<=\s))@[A-Za-z0-9_.]+")
LINK_RE = re.compile(r"https?://\S+|www\.\S+|(?<![@\w])[A-Za-z0-9-]+\.(?:com|ir|net|org|io|ai|co|me|app|dev)(?:/\S*)?", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")
L = rf"(?<![A-Za-z{LETTERS}{ZWNJ}])"   # start of a word
R = rf"(?![A-Za-z{LETTERS}{ZWNJ}])"    # end of a word


def normalize(text):
    """For matching only: Arabic yeh and kaf to Persian, no tatweel, one kind of space."""
    t = str(text or "").replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ـ", "")
    return re.sub(r"[   ]", " ", t)


def latin_digits(s):
    return str(s).translate(str.maketrans(FA_DIGITS + AR_DIGITS, "0123456789" * 2))


def fa_digits(s):
    return str(s).translate(str.maketrans("0123456789", FA_DIGITS))


def words(text):
    """Words, with the half-space kept inside them («می‌خوام» is one word) and «۱۸,۰۰۰» as one."""
    return [w.strip(ZWNJ + "'’.,٫٬-") for w in WORD_RE.findall(normalize(text)) if w.strip(ZWNJ + "'’.,٫٬-")]


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(normalize(text)) if len(words(s)) > 2]


def squash(w):
    """One spelling for comparing words: no half-space or space, Persian letters."""
    return normalize(w).replace(ZWNJ, "").replace(" ", "").lower()


def phrase_re(phrase):
    """A word or phrase as a regex that tolerates «می‌خوام» / «می خوام» / «میخوام» and ی/ي."""
    parts = [re.escape(p) for p in re.split(rf"[\s{ZWNJ}]+", normalize(phrase).strip()) if p]
    body = rf"[\s{ZWNJ}]*".join(parts)
    return re.compile(L + body + R, re.I)


@lru_cache(maxsize=None)
def data(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def lex():
    return data("slop_fa.json")


@lru_cache(maxsize=None)
def wordset(key):
    return {squash(w) for w in lex().get(key, [])}


def number_words():
    return wordset("number_words")


def money_words():
    return wordset("money_words")


def time_units():
    return wordset("time_units")


def concrete_markers(text):
    """Numbers, Latin names, quoted terms and spoken numbers/money: the checkable things in a line."""
    t = normalize(text)
    nums = [n.strip() for n in NUMBER_RE.findall(t) if n.strip()]
    names = sorted({n for n in LATIN_NAME_RE.findall(t) if not LINK_RE.fullmatch(n)})
    quoted = QUOTED_RE.findall(t)
    spoken = [w for w in words(t) if squash(w) in number_words() or squash(w) in money_words()]
    return nums, names, quoted, spoken


def register(text):
    """(colloquial hits, formal hits): spoken «می‌کنه، اینو، یه» against written «می‌کند، را، یک»."""
    t = normalize(text)
    col = sum(len(re.findall(p, t, re.M)) for p in lex().get("colloquial_markers", []))
    form = sum(len(re.findall(p, t, re.M)) for p in lex().get("formal_markers", []))
    return col, form


def pronoun_hits(text):
    t = normalize(text)
    return sum(len(re.findall(p, t, re.M)) for p in lex().get("pronouns", []))
