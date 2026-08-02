from epyhia.ingest.extractors import extract_site_text, extract_video_props_content

_HTML = """
<html>
<head>
  <meta name="description" content="A site for 120 things">
  <style>.hero { color: #0a0a0a; font-size: 1.5rem; transition: 0.3s; }</style>
</head>
<body>
  <svg viewBox="0 0 100 100"></svg>
  <h1 title="Welcome" data-product="basic-plan">Hello world</h1>
  <img alt="logo" src="x.png">
  <script>var price = 42; console.log(price);</script>
  <p aria-label="note">Plain paragraph text</p>
</body>
</html>
"""

_PROPS = {
    "archetype_id": "a1",
    "content": {
        "headline": "Big Sale",
        "scenes": [
            {
                "kind": "price",
                "lines": ["only"],
                "values": [{"label": "Basic", "amount_minor": 12000, "currency": "USD"}],
            }
        ],
    },
    "style": {
        "palette": {"primary": "#0a0a0a"},
        "type": {"size": 24},
        "motion_intensity": "high",
    },
}


def test_site_extractor_ignores_css_and_markup_values() -> None:
    texts = extract_site_text(_HTML)
    joined = " ".join(texts)

    for out_of_scope in ("#0a0a0a", "1.5rem", "0.3s", "0 0 100 100", "basic-plan", "42"):
        assert out_of_scope not in joined


def test_site_extractor_captures_in_scope_text() -> None:
    texts = extract_site_text(_HTML)

    assert "A site for 120 things" in texts  # meta description
    assert "Welcome" in texts  # title attr
    assert "logo" in texts  # alt attr
    assert "note" in texts  # aria-label attr
    assert "Hello world" in texts  # text node
    assert "Plain paragraph text" in texts  # text node


def test_video_props_extractor_reads_content_and_skips_style() -> None:
    leaves = extract_video_props_content(_PROPS)

    assert "Big Sale" in leaves
    assert "12000" in leaves
    assert "USD" in leaves

    for style_only in ("#0a0a0a", "24", "high"):
        assert style_only not in leaves
