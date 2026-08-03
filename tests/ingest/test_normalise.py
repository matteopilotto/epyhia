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
