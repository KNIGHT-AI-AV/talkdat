# Talk DAT! sector benchmarks

Median ms per call, win32, measured 2026-08-17. Regenerate with
`python scripts/benchmark_sectors.py` and diff this file in the release
commit whenever a sector changes.

| Sector | Function | Median ms | Note |
|---|---|---|---|
| formatting | heuristic_format (300-word ramble) | 3.555 |  |
| formatting | apply_spoken_punctuation | 0.228 |  |
| formatting | strip_em_dashes (dash-heavy text) | 0.034 |  |
| vocabulary | apply_vocabulary (defaults+brands, 300 words) | 81.219 |  |
| pipeline | process_dictation local rules end-to-end | 91.056 |  |
| pipeline | is_bare_fragment | 0.001 |  |
| pill | scrolling_spectrum_frame (warm crop) | 0.015 |  |
| pill | apply_metallic_sheen | 3.912 |  |
| pill | standby gray frame | 0.772 |  |
| config | load_config (merge + migrations) | 3.176 |  |
| config | save_config (anti-clobber union) | 71.336 |  |
| journal | record_formatting (one entry) | 0.737 |  |
| journal | journal_tail (50-entry file) | 0.316 |  |
| hotkeys | chord_conflicts (full map) | 0.032 |  |
| session | likely_has_input_signal (1s silence) | 1.049 |  |
