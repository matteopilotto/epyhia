import re
from dataclasses import dataclass
from decimal import Decimal

# Currencies whose minor unit is not 1/100th of the major unit. Anything absent
# defaults to 2 (research.md R6). Public because reading minor units back out is the
# same table read backwards: the pack's storyboard companion renders `amount_minor` with
# it, and a second table that disagreed would print the wrong money (002 research R7).
MINOR_EXPONENT = {"JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3, "OMR": 3}

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
# "$" names a family of currencies, not one, and so does the word "dollars". Which dollar a
# bare symbol means is a fact about the brief's locale, never a constant (Principle I):
# the first en-AU brief through the system had its correct "$349" read as USD and held as
# fabricated against a grounding set that knew the amount as AUD. Region-scoped the same
# way _WORD_MAPS is language-scoped; a locale without a region, or a region not listed,
# keeps the symbol's conventional reading, so en-US and bare-language locales behave as
# before. An explicit ISO code in the text is never overridden — only the bare symbol and
# the bare word are ambiguous.
_DOLLAR_BY_REGION = {"US": "USD", "AU": "AUD", "CA": "CAD", "NZ": "NZD", "SG": "SGD", "HK": "HKD"}
_DOLLAR_WORDS = {"dollar", "dollars"}
_ISO_CODE_RE = re.compile(r"\b[A-Z]{3}\b")
_SEPARATOR_CHARS = ",. '"
# The class between the two digits is exactly `_SEPARATOR_CHARS`, and has to stay that way:
# whatever the token may contain, `_parse_digit_token` strips with that string and hands the
# rest to `Decimal`. `\s` here read wider than the stripper — a line break survived it and
# turned "6.50\n15.00" into one unparseable token — and it is the wrong reading anyway. A
# space separates thousands; a newline ends the number, exactly as it does for number words.
_DIGIT_TOKEN_RE = re.compile(r"\d[\d,. ']*\d|\d")

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}

_WORD_MAPS = {"en": {**_ONES, **_TENS, **_SCALES}}

# A phone number is a label that happens to be spelled with digits, not a quantity.
# Shredding one into 1 / 503 / 555 grounds three arbitrary values *and* flags a site
# for printing its own number. Masking it here puts the exclusion on both sides of the
# set difference at once, since brief and artifact are scanned by this same function.
# Hyphen- and paren-separated only: thousands separators are dots and spaces, so no
# number format can collide with this.
_PHONE_RE = re.compile(r"\+?\d+(?:-\d+){2,}|\(\d+\)[\s-]*\d+(?:-\d+)*")

_CURRENCY_WORDS = {
    "dollars": "USD", "dollar": "USD",
    "euros": "EUR", "euro": "EUR",
    "pounds": "GBP", "pound": "GBP",
    "yen": "JPY",
}
_WORD_RE = re.compile(r"[A-Za-z]+")
# What may sit between two number words and still leave them one written number: the space
# of "one hundred twenty three" and the hyphen of "twenty-three", and nothing else. A full
# stop or a line break ends the run, so "gone by nine." followed by "Three ways" stays two
# numbers instead of summing into a twelve that nobody wrote.
_RUN_GAP_RE = re.compile(r"[ \t-]*")


@dataclass(frozen=True)
class GroundingEntry:
    value: Decimal
    currency: str | None = None


def words_to_number(text: str, locale: str) -> Decimal | None:
    """Maps locale-scoped spelled-out numbers to digits, so spelling a number out is not
    a way around the grounding check (FR-006)."""
    lang = locale.split("-")[0].lower()
    words_map = _WORD_MAPS.get(lang)
    if not words_map:
        return None

    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    if not tokens or any(token not in words_map for token in tokens):
        return None

    total = 0
    current = 0
    for token in tokens:
        scale = words_map[token]
        if scale == 100:
            current = (current or 1) * scale
        elif scale >= 1_000:
            current = (current or 1) * scale
            total += current
            current = 0
        else:
            current += scale
    return Decimal(total + current)


def _parse_digit_token(token: str) -> Decimal:
    """Distinguishes a decimal separator from a thousands separator: the last
    separator is decimal only if exactly 1-2 digits follow it."""
    seps = [i for i, c in enumerate(token) if c in _SEPARATOR_CHARS]
    if not seps:
        return Decimal(token)

    last_sep = seps[-1]
    decimal_digits = len(token) - last_sep - 1
    if decimal_digits in (1, 2):
        integer_part = re.sub(f"[{re.escape(_SEPARATOR_CHARS)}]", "", token[:last_sep])
        decimal_part = token[last_sep + 1 :]
        return Decimal(f"{integer_part}.{decimal_part}")
    return Decimal(re.sub(f"[{re.escape(_SEPARATOR_CHARS)}]", "", token))


def _region(locale: str) -> str | None:
    parts = locale.split("-")
    return parts[1].upper() if len(parts) > 1 else None


def _detect_currency(text: str, region: str | None = None) -> tuple[str | None, str]:
    """Finds a currency symbol or ISO code and strips it out, returning the
    currency (if any) and the remaining text. A bare dollar sign resolves
    through the brief's own region rather than to a fixed currency."""
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            if symbol == "$":
                code = _DOLLAR_BY_REGION.get(region, code)
            return code, text.replace(symbol, "").strip()

    iso_match = _ISO_CODE_RE.search(text)
    if iso_match:
        currency = iso_match.group(0)
        return currency, text.replace(currency, "").strip()

    return None, text.strip()


def _to_minor(value: Decimal, currency: str | None) -> Decimal:
    """Reduces an amount to minor units when a currency is present (FR-006)."""
    if currency is None:
        return value
    minor_exponent = MINOR_EXPONENT.get(currency, 2)
    return (value * (10**minor_exponent)).quantize(Decimal(1))


def normalise_amount(raw: str, locale: str) -> GroundingEntry | None:
    """Strips separators and currency symbols, maps number words to digits, and
    reduces the amount to minor units when a currency is present (FR-006)."""
    currency, text = _detect_currency(raw.strip(), _region(locale))

    digit_match = _DIGIT_TOKEN_RE.search(text)
    if digit_match:
        value = _parse_digit_token(digit_match.group(0))
    else:
        value = words_to_number(text, locale)
        if value is None:
            return None

    return GroundingEntry(value=_to_minor(value, currency), currency=currency)


def find_amounts(text: str, locale: str) -> list[GroundingEntry]:
    """Scans free text for every numeral it carries — digit tokens with a nearby
    currency marker, and spelled-out runs of number words — so a fabricated
    amount cannot hide in prose (FR-006, spec.md "spelling a number out is not
    a way around the check"). Phone-shaped tokens are identifiers rather than
    quantities and are excluded from both sides of the comparison."""
    entries = []
    text = _PHONE_RE.sub(" ", text)
    region = _region(locale)

    for match in _DIGIT_TOKEN_RE.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 4) : min(len(text), end + 4)]
        currency, _ = _detect_currency(window, region)
        value = _to_minor(_parse_digit_token(match.group(0)), currency)
        entries.append(GroundingEntry(value=value, currency=currency))

    lang = locale.split("-")[0].lower()
    words_map = _WORD_MAPS.get(lang, {})
    tokens = list(_WORD_RE.finditer(text))
    i = 0
    while i < len(tokens):
        word = tokens[i].group(0).lower()
        if word not in words_map:
            i += 1
            continue

        j = i
        while (
            j + 1 < len(tokens)
            and tokens[j + 1].group(0).lower() in words_map
            and _RUN_GAP_RE.fullmatch(text[tokens[j].end() : tokens[j + 1].start()])
        ):
            j += 1

        run_text = " ".join(t.group(0) for t in tokens[i : j + 1])
        value = words_to_number(run_text, locale)
        currency = None
        if j + 1 < len(tokens):
            word_after = tokens[j + 1].group(0).lower()
            currency = _CURRENCY_WORDS.get(word_after)
            if word_after in _DOLLAR_WORDS:
                currency = _DOLLAR_BY_REGION.get(region, currency)

        if value is not None:
            entries.append(GroundingEntry(value=_to_minor(value, currency), currency=currency))

        i = j + 1

    return entries
