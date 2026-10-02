# RF Measurement Analyzer

A local RF engineering portfolio project. Load two `.s2p` files, compare frequency
responses, check a filter against requirements, identify worst frequencies and signed
margins, and export the evidence as standalone HTML or full-resolution CSV.

The dashboard is at **http://127.0.0.1:8003/**. It opens with two demonstration filters:
nominal **PASS** and degraded **FAIL**. All demo values are **synthetic circuit data**,
not VNA measurements. The parser also accepts supported user-supplied Touchstone files.

Russian quick start: [START_HERE.md](START_HERE.md).

## Run locally

Tested on macOS Apple Silicon with Python 3.9.6.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-cache-dir -r requirements.lock.txt
python run.py
```

Open **http://127.0.0.1:8003/**. Keep the terminal open; Ctrl+C stops the server.
On macOS, `start.command` does this automatically (installs dependencies only when
creating a missing environment). On the development Mac the environment is ready.

No frontend build, CDN, Node installation, or cloud account is needed. The main dashboard
uses local HTML/CSS/JavaScript and SVG. FastAPI's optional `/docs` uses CDN Swagger assets.
If port 8003 is occupied:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8004
```

## Demo in one minute

1. Compare green nominal and orange degraded S21. Select the two result cards.
2. Nominal peak is 2.450 GHz. Degraded peak is 2.540 GHz; at the requested band edge,
   loss reaches 3.63 dB and return loss drops to 9.50 dB.
3. Switch to S11/S22, all four S-parameters, and group delay. Hover for nearby sampled values.
4. Adjust requirements and press **Проверить требования**. Unapplied edits disable report export.
5. Download both source `.s2p` files, the HTML report, or CSV. Try uploading a downloaded file.
6. A file containing only the passband receives **INCOMPLETE**, because the stopbands are missing.

## What is implemented

- Bounded Touchstone 1.0 S2P reader: RI, MA and DB, Hz/kHz/MHz/GHz, option defaults and
  case/order handling, comments, wrapped records, equal real reference impedance.
- Correct two-port order: S11, S21, S12, S22. Strictly increasing positive frequency grid.
- Four independent checks: maximum in-band loss, minimum return loss on **both** ports,
  lower and upper stopband attenuation. Inclusive limits and signed margins.
- PASS / FAIL / INCOMPLETE. Partial coverage never produces a full PASS or full FAIL;
  individual confirmed violations remain visible.
- Peak S21, connected -3 dB bandwidth around the global sampled peak, and approximate group delay.
- Passive-network and reciprocity diagnostics. These are informational, not hidden acceptance criteria.
- Uploaded-file SHA-256 provenance; demo identity is recognized by content, not filename.
- Two-file overlays on independent frequency grids; no extrapolation or implicit impedance renormalization.
- Reports containing actual requirements, source hashes, worst frequencies and evaluation method.

Uploads stay in server memory, with at most 32 uploaded networks retained (LRU eviction).
They disappear when the server restarts. No uploads are written to disk or sent to a cloud.
This is a single-user localhost application, not an authenticated multi-user service.

## Circuit model behind the synthetic files

The generator uses an ideal third-order Butterworth low-pass prototype `g=(1,2,1)`
transformed into a band-pass ladder: **series LC — shunt parallel LC — series LC**.
Both ports have real reference impedance `Z0=50 ohm`. With `w0=2*pi*f0` and fractional
bandwidth `b=0.14`:

```text
series: L = g*Z0/(w0*b),   C = b/(g*Z0*w0)
shunt:  C = g/(Z0*w0*b),   L = Z0*b/(g*w0)

Z = Rs + j*(w*Ls - 1/(w*Cs))
Y = 1/Rp + j*(w*Cp - 1/(w*Lp))
ABCD = [1 Z;0 1] [1 0;Y 1] [1 Z;0 1]
den = A + B/Z0 + C*Z0 + D
S11 = (A + B/Z0 - C*Z0 - D)/den
S21 = 2/den; S12 = S21 (reciprocal ladder)
S22 = (-A + B/Z0 - C*Z0 + D)/den
```

Nominal: `f0=2.450 GHz`, each series resistance `1.6 ohm`, shunt resistance `2500 ohm`.
Degraded: `f0=2.540 GHz`, each series resistance `9 ohm`, shunt resistance `650 ohm`.
The degradation changes the resonance and dissipative losses, rather than drawing
arbitrary curves. Both networks are passive and reciprocal. Component values and
assumptions are saved in [examples/model.json](examples/model.json).

This is an **ideal lumped model**. At GHz frequencies the small component values and
parasitics would need physical validation and an EM/distributed model. There is no
claim that this is a manufacturable filter design or a prediction of specific hardware.

Regenerate the files deterministically:

```bash
.venv/bin/python scripts/generate_examples.py
```

## Calculation and coverage rules

- Loss: `-20*log10(abs(S21))`; return loss: worst of `-S11_dB` and `-S22_dB`.
- Each requested band needs full coverage and at least three native frequency points.
  Check every native sample in the band plus linearly interpolated **dB** boundary values.
  This does not certify behaviour between samples. A coarse grid produces a warning.
- Margin: `limit-actual` for maximum limits, `actual-limit` for minimum limits.
- Bandwidth: contiguous region at/above sampled peak minus 3 dB. Crossing frequencies
  are interpolated in dB. Missing crossings produce an unavailable result, not extrapolation.
- Group delay: `-d(unwrap(angle(S21)))/d(f)/(2*pi)`. Unwrap contiguous segments independently;
  mask values with S21 <= -60 dB and valid segments shorter than three points.
  Phase aliasing on coarse grids is possible; delay is not an acceptance requirement.
- S magnitudes use a -300 dB numerical floor for exact/near zeros. Plots may clip very low
  values; tables/CSV retain calculation values at the documented numerical floor.
- All native data are used for calculations/CSV. Display curves are reduced to approximately
  2000 points, retaining each requirement's nearest worst point and the global peak.

Supported input: text ASCII/UTF-8, `.s2p`, <=2 MiB, 3–20,000 samples, frequencies 1 Hz–1000 THz.
Unsupported: Touchstone 2.x keywords, mixed-mode parameters, Y/Z/H/G conversion, noise
blocks, per-port complex/different reference impedances, duplicate/descending frequency.
Unsupported inputs fail with an explanation. This is a focused reader, not a complete
Touchstone implementation. Format reference: [IBIS Touchstone specification](https://www.ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf),
including the legacy Version 1.0 rules.

## Architecture and stack

```text
Browser files + requirements
    FastAPI local HTTP API
    Touchstone reader -> immutable NumPy network arrays
    analysis -> sample coverage, extrema, margins, delay, bandwidth
    HTML/SVG and CSV evidence
```

| File                | Purpose                                                                      |
| ------------------- | ---------------------------------------------------------------------------- |
| `app/touchstone.py` | Parse and validate input; preserve complex S-parameters                      |
| `app/circuit.py`    | Circuit equations and deterministic demo generator                           |
| `app/analysis.py`   | Requirements, coverage, engineering metrics and verdict                      |
| `app/main.py`       | Local API and bounded in-memory upload store                                 |
| `app/reports.py`    | Standalone report and full-resolution numerical CSV                          |
| `app/static/`       | Browser interface and SVG plots                                              |
| `tests/`            | Independent numerical fixtures, circuit checks, parsing and API verification |

Python / NumPy / FastAPI / Pydantic / pytest / HTTPX / HTML / CSS / JavaScript / SVG / Git.
No pandas, scikit-rf, Plotly, instrument driver, database or ML is claimed in this version.
`requirements.txt` pins direct dependencies; `requirements.lock.txt` is the verified full
dependency snapshot. Black and Prettier were formatting tools, not application requirements.

## Verify

```bash
.venv/bin/python -m pytest -q
# With the server running:
.venv/bin/python scripts/live_check.py
.venv/bin/python scripts/live_check.py --save-examples
```

Tests use independent nonreciprocal matrix fixtures (to detect wrong port ordering),
analytic resonance loss, lossless power conservation, known phase slope, inclusive
boundaries, incomplete coverage, rejection paths, exports and upload limits.
See [VERIFICATION.md](VERIFICATION.md) for checked behaviour and practical limits.

Sample outputs: [HTML report](examples/sample-report.html), [CSV](examples/sample-measurements.csv),
[live check summary](examples/live-results.json). Demo files are synthetic and labeled as such.

## Portfolio positioning

Personal, AI-assisted engineering project demonstrating RF data processing and verification
automation. It is not commercial software experience, actual VNA control, calibration,
hardware qualification, a production deployment or a substitute for understanding the code.
Reproduce the demo and explain the model/calculation conventions before using it in an interview.
