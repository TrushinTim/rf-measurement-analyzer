# Verification record

Checked on 2026-10-02, macOS Apple Silicon, Python 3.9.6.

## Passed

- **52 pytest cases**, final result `52 passed in 0.69s`.
- Parser fixtures for every RI/MA/DB and Hz/kHz/MHz/GHz combination. Independent
  nonreciprocal matrices check S21/S12 ordering rather than assuming reciprocity.
- BOM/comments/wrapped records, option defaults/order, impedance and invalid-file handling.
- Analytic center-frequency transmission, reciprocity/passivity, and lossless power conservation.
- Known 2.5 ns delay from an independently defined phase slope; connected bandwidth crossings.
- Inclusive limits, negative margins, both-port return loss, missing frequency coverage,
  insufficient sampling, zero-transmission masking and nonfinite input handling.
- Actual server HTTP checks: nominal PASS, degraded FAIL, upload round-trip, partial
  INCOMPLETE, malformed-file 422, standalone HTML and 1201-point CSV.
- Dashboard logic exercised in JSDOM against the live HTTP server: all four plot modes,
  A/B selection, changed limits, blocked stale report export, valid/invalid uploads,
  different-reference rejection with previous-file preservation, partial results,
  one-file mode and reset to demos. No JavaScript runtime errors.
- Installed Chrome loaded the dashboard; its accessible page text confirmed both
  demo cards, PASS/FAIL, computed metrics and all four requirement rows.
- JavaScript syntax check; Python/HTML/CSS/JS formatting; `pip check`; Git whitespace check.
- `requirements.lock.txt` records the verified application/test dependencies. Formatting
  tools and the temporary JSDOM environment are not required to run the application.

Saved evidence: `examples/live-results.json`, `examples/sample-report.html`,
`examples/sample-measurements.csv`, and the two source `.s2p` files with `model.json`.

## Practical limits

- JSDOM tests DOM logic; they do not verify actual browser layout or pixel rendering.
  The native screenshot tool returned a blank/grey capture, so no screenshot-based
  desktop/mobile visual acceptance is claimed. A responsive stylesheet is implemented.
- Native Chrome loading is checked; automated real-browser upload/download and cross-browser
  visual tests are not claimed. Upload/download endpoints were verified through real HTTP.
- These are synthetic LC-network files. No VNA, physical filter, calibration, EM model,
  measurement uncertainty or hardware qualification has been verified.
- Touchstone support is deliberately limited to the documented Version 1.0 two-port
  S-parameter subset. This does not claim a complete standard implementation.
- Frequency checks operate on samples and interpolated boundaries. They cannot prove
  absence of a narrow violation between samples. Phase aliasing can affect group delay.
- Uploaded files live only in bounded process memory. No authentication, cloud deployment,
  instrument control, database, Docker runtime or CI pipeline is part of this project.
- Final launch uses **port 8003**. An earlier preview remains on 8002 because the execution
  environment denied both terminal interruption and process signalling. It was not
  used for the final live verification; future `start.command` launches use 8003.

## Reproduce

```bash
.venv/bin/python -m pytest -q
.venv/bin/python run.py
# In a second terminal:
.venv/bin/python scripts/live_check.py
```

The optional local DOM verification used JSDOM 26.1.0 under ignored `work/ui-check/`;
it is verification tooling, not a frontend build dependency or a Playwright test suite.
