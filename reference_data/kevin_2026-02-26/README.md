# Kevin's reference data (2026-02-26)

Copied from Downloads. Use to recreate or compare against Kevin's 10,000-run results.

| File | Description |
|------|-------------|
| `fire_load_distr 1.txt` | One fire load (MJ/m²) per line — input for each run. |
| `opening_perc_factored_distr 1.txt` | One glazing/opening fraction (0–1) per line — input for each run. |
| `test_run_10000_plots.rar` | Output plots from the 10k run. |
| `test_run_10000_csvs.rar` | Output CSVs from the 10k run. |
| `run00000_...pdf` | Single-run report; values match line 1 of the two .txt files. |

To recreate runs: build `runs: [ { fire_load, glazing_breakage }, ... ]` by pairing line *i* of the two .txt files, and use the same fixed/beams config Kevin used (not included here).
