from epyhia.ingest.normalise import find_amounts


def test_adjacent_tokens_do_not_contaminate_each_other() -> None:
    """Regression test: normalise_amount used to re-search the ±4-character window
    for its own digit token, so '2024' in '2020-2024 season' could be read back as
    the partial token '20' from a neighbouring match."""
    entries = find_amounts("2020-2024 season", "en-US")

    assert {(str(e.value), e.currency) for e in entries} == {("2020", None), ("2024", None)}


def test_currency_context_is_still_read_from_the_window() -> None:
    """The ±4-character window exists to supply currency context; the fix must not
    regress that into reading currency purely from the matched token itself."""
    assert [(str(e.value), e.currency) for e in find_amounts("$120.00 a month", "en-US")] == [
        ("12000", "USD")
    ]
    assert [(str(e.value), e.currency) for e in find_amounts("Price 1.234,56 EUR", "en-US")] == [
        ("123456", "EUR")
    ]


def test_number_formats_survive_unchanged() -> None:
    cases = {
        "1.234,56": ("1234.56", None),
        "1,234.56": ("1234.56", None),
        "$120.00": ("12000", "USD"),
        "1 234 567": ("1234567", None),
        "2016": ("2016", None),
    }
    for text, expected in cases.items():
        entries = find_amounts(text, "en-US")
        assert [(str(e.value), e.currency) for e in entries] == [expected]

    entries = find_amounts("twelve dollars", "en-US")
    assert [(str(e.value), e.currency) for e in entries] == [("1200", "USD")]


def test_a_number_word_run_stops_at_the_end_of_a_sentence() -> None:
    """Regression test: the run extended to the next number word whatever lay between them,
    so a sentence ending on one and the next beginning on one were summed into an amount
    nobody wrote. Found on a real email whose copy was correct — the phantom was ungrounded
    by construction, and on a site artifact that is a refused deploy for a clean page."""
    entries = find_amounts("gone by nine.\n\nThree ways to reserve:", "en-GB")

    assert [str(e.value) for e in entries] == ["9", "3"]


def test_a_digit_run_stops_at_the_end_of_a_line() -> None:
    """The same defect on the digit side, and this one raised rather than lying: the token
    could span any whitespace but the stripper only knew a literal space, so a line break
    reached `Decimal` intact and took the whole stage down with a ConversionSyntax. Found on
    a real pack whose copy was correct."""
    entries = find_amounts("ready 6.50\n15.00 box", "en-GB")

    assert [str(e.value) for e in entries] == ["6.50", "15.00"]
    assert [str(e.value) for e in find_amounts("from 7\n2 loaves", "en-GB")] == ["7", "2"]


def test_a_digit_run_still_spans_a_thousands_space() -> None:
    """The other side of that fix: a space between digits is a thousands separator and must
    keep reading as one number."""
    assert [str(e.value) for e in find_amounts("1 000 000 loaves", "en-GB")] == ["1000000"]


def test_a_written_number_still_spans_its_own_spaces_and_hyphen() -> None:
    """The other side of that fix: the separators that do belong inside one written number
    must keep reading as one, or spelling a number out becomes a way around the check."""
    assert [str(e.value) for e in find_amounts("twenty-three", "en-US")] == ["23"]
    assert [str(e.value) for e in find_amounts("one hundred twenty three", "en-US")] == ["123"]
