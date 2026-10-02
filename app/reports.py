import csv
from datetime import datetime, timezone
from html import escape
import io
import json
import numpy as np
from .analysis import magnitude_db


def fmt(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def report_svg(datasets, requirements):
    all_f = [f for d in datasets for f in d["plot"]["frequency_ghz"]]
    lo, hi = min(all_f), max(all_f)
    values = [v for d in datasets for v in d["plot"]["db"]["S21"]]
    bottom, top = max(-120, min(-40, min(values) - 3)), max(3, max(values) + 3)
    def x(f): return 65 + (f - lo) / (hi - lo) * 870
    def y(v): return 25 + (top - max(bottom, min(top, v))) / (top - bottom) * 290
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 360" role="img" aria-label="S21 in dB">', '<rect width="980" height="360" fill="#f5f8fb"/>']
    left, right = max(lo, requirements["pass_start_ghz"]), min(hi, requirements["pass_end_ghz"])
    if left < right:
        parts.append(f'<rect x="{x(left):.2f}" y="25" width="{x(right)-x(left):.2f}" height="290" fill="#d8f3e7"/>')
    for v in np.linspace(bottom, top, 6):
        parts.append(f'<path d="M65 {y(v):.2f}H935" stroke="#d9e0e9"/><text x="55" y="{y(v)+4:.2f}" text-anchor="end" font-size="12">{v:.1f}</text>')
    for f in np.linspace(lo, hi, 7):
        parts.append(f'<text x="{x(f):.2f}" y="340" text-anchor="middle" font-size="12">{f:.3f}</text>')
    for i, d in enumerate(datasets):
        coordinates = " ".join(f"{x(f):.2f},{y(v):.2f}" for f, v in zip(d["plot"]["frequency_ghz"], d["plot"]["db"]["S21"]))
        parts.append(f'<polyline points="{coordinates}" fill="none" stroke="{["#008f85", "#c05837"][i]}" stroke-width="2"/>')
    parts.append('<text x="8" y="18" font-size="12">S21, dB</text><text x="950" y="355" text-anchor="end" font-size="12">GHz</text></svg>')
    return "".join(parts)


def html_report(result):
    sections = []
    for d in result["datasets"]:
        rows = []
        for c in d["checks"]:
            criterion = ("≤" if c["sense"] == "max" else "≥") + f' {c["limit"]:g} dB'
            rows.append(f'<tr><td>{escape(c["code"])}</td><td>{escape(c["label"])}<br>{c["start_ghz"]:g}–{c["end_ghz"]:g} GHz</td><td>{criterion}</td><td>{fmt(c["actual"])} dB<br>{fmt(c["worst_frequency_ghz"])} GHz</td><td>{fmt(c["margin_db"])} dB</td><td>{c["status"]}<br>{escape(c["reason"] or "")}</td></tr>')
        warnings = "".join(f"<li>{escape(w)}</li>" for w in d["warnings"])
        source = "SYNTHETIC — LC circuit simulation" if d["source"] == "synthetic" else "Uploaded file — provenance not independently verified"
        sections.append(f'<section><h2>{escape(d["name"])} · {d["verdict"]}</h2><p>{source}. {d["points"]} points; reference {d["reference_ohm"]:g} Ω.<br>SHA-256: <code>{d["sha256"]}</code></p><p>Peak: {fmt(d["peak_frequency_ghz"])} GHz / {fmt(d["peak_s21_db"])} dB. Connected −3 dB bandwidth: {fmt(d["bandwidth"]["width_mhz"])} MHz.</p><table><thead><tr><th>ID</th><th>Requirement / band</th><th>Limit</th><th>Worst result</th><th>Margin</th><th>Status</th></tr></thead><tbody>{"".join(rows)}</tbody></table><ul>{warnings}</ul></section>')
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    req_json = escape(json.dumps(result["requirements"], indent=2))
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>RF Measurement Analyzer · Report</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;color:#193144;max-width:1100px;margin:35px auto;padding:0 25px}}h1,h2{{line-height:1.25}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:12px;border:1px solid #d5dee8;vertical-align:top}}th{{background:#eef3f7}}section{{margin:30px 0;break-inside:avoid}}code{{overflow-wrap:anywhere}}pre{{background:#eef3f7;padding:16px}}svg{{width:100%}}.note{{padding:15px;background:#fff4db;border-left:4px solid #bc7e19}}@media print{{body{{margin:0}}}}</style>
<h1>RF Measurement Analyzer</h1><p>Filter acceptance report · {now} (UTC)</p>
<p class="note">Results apply to the supplied sampled data. Demo files are synthetic; no real VNA measurement, hardware qualification, calibration or uncertainty assessment is claimed.</p>
{report_svg(result["datasets"], result["requirements"])}<p>S21: green = file A, orange = file B. Green band = specified passband.</p>
{"".join(sections)}<h2>Evaluation method</h2><p>Loss = −20 log₁₀|S21|. Return loss = min(−20 log₁₀|S11|, −20 log₁₀|S22|). Limits are inclusive. Each requested band requires full frequency coverage and at least three native samples. Native samples and linearly interpolated boundary values in dB are checked. No extrapolation or certification between samples. Any unevaluated requirement makes the overall verdict INCOMPLETE; individual failures remain visible. Group delay uses unwrapped S21 phase; values below −60 dB are masked. Numerical magnitude floor: −300 dB.</p><h2>Requirements snapshot</h2><pre>{req_json}</pre></html>'''


def measurement_csv(network):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["frequency_hz", "S11_db", "S21_db", "S12_db", "S22_db",
                     "S11_phase_deg", "S21_phase_deg", "S12_phase_deg", "S22_phase_deg"])
    db = magnitude_db(network.s)
    phase = np.angle(network.s, deg=True)
    for index, f in enumerate(network.frequency):
        ordered = [(0, 0), (1, 0), (0, 1), (1, 1)]
        writer.writerow([f"{f:.12g}"] + [f"{db[index, i, j]:.12g}" for i, j in ordered] + [f"{phase[index, i, j]:.12g}" for i, j in ordered])
    return output.getvalue()
