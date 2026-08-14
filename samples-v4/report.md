# Direction sample — 2026-08-14

strategist prompt v4 · REAL model · 4 samples × 2 fixtures · $2.71

## Within one (n=4)

    pairing     zilla-slab/ibm-plex-sans ×2, jetbrains-mono/source-serif-4 ×1, jetbrains-mono/libre-baskerville ×1
                modal zilla-slab/ibm-plex-sans — 2/4 draws each
    archetype   split_technical ×3, dense_index ×1
    layouts     hero_split ×4, split_manifesto ×4, numbered_process ×4, offer_table ×4, stat_band ×4, faq_accordion ×4, contact_block ×4, feature_rows ×3, proof_strip ×1
    palette ΔE  accent max 100.4, median 50.8 · bg max 2.3, median 1.4
    medoid      {"accent": "#C1440E", "bg": "#F4EFE6", "fg": "#241C17", "muted": "#6E6155"}
    narrated    4/4 draws wrote their drafting out in response text

## Within two (n=4)

    pairing     zilla-slab/ibm-plex-sans ×2, archivo-black/ibm-plex-sans ×2
                modal archivo-black/ibm-plex-sans, zilla-slab/ibm-plex-sans — 2/4 draws each
    archetype   split_technical ×4
    layouts     hero_split ×4, split_manifesto ×4, numbered_process ×4, offer_table ×4, feature_rows ×4, stat_band ×4, faq_accordion ×4, contact_block ×4, sticky_rail ×1
    palette ΔE  accent max 15.1, median 7.8 · bg max 3.4, median 1.9
    medoid      {"accent": "#B4491A", "bg": "#EDE9E1", "fg": "#17181A", "muted": "#6A665E"}
    narrated    4/4 draws wrote their drafting out in response text

## Across fixtures

### one × two

    shared pairings   zilla-slab/ibm-plex-sans
    shared archetypes split_technical

    ΔE bg
             0      1      2      3
    0      0.7    3.8    2.5    2.0
    1      2.1    5.3    3.3    3.9
    2      0.8    3.9    2.2    2.3
    3      1.5    4.4    2.2    3.0

    ΔE fg
             0      1      2      3
    0      7.5    9.9   11.9   12.7
    1      4.0    6.8    9.1    9.1
    2      5.2    7.0    8.7   10.0
    3      3.7    5.6    7.6    8.6

    ΔE accent
             0      1      2      3
    0      5.4    8.0    5.3   11.7
    1     95.5   89.2   89.7   87.8
    2      9.3   11.7   10.9   14.6
    3      7.9   10.6    9.4   13.6

    ΔE muted
             0      1      2      3
    0      4.6    4.6    6.3   11.2
    1      6.0    3.9    5.7    9.5
    2      6.2    4.5    6.6   10.8
    3      4.6    2.9    4.9    9.3

    SC-001, measured over the samples:
      [FAIL] modal pairings differ — {zilla-slab/ibm-plex-sans} vs {archivo-black/ibm-plex-sans, zilla-slab/ibm-plex-sans}
      [FAIL] modal palettes are different directions — ΔE accent 9.4 (bar 20), bg 2.2 (bar 10)
      [FAIL] modal archetypes differ — {split_technical} vs {split_technical}
    verdict: NOT MET

