"""Ideal lumped-element third-order Butterworth band-pass ladder.

Low-pass prototype g=(1,2,1), impedance 50 ohm, series/shunt/series.
With w0=2*pi*f0 and fractional bandwidth b:
series L=g*Z0/(w0*b), C=b/(g*Z0*w0);
shunt  C=g/(Z0*w0*b), L=Z0*b/(g*w0).
Positive series R and shunt G model dissipative losses. No EM/parasitics.
"""
import json
from pathlib import Path
import numpy as np


def simulate(frequency, center=2.45e9, fractional_bw=0.14,
             series_r=1.6, shunt_r=2500.0, z0=50.0):
    f = np.asarray(frequency, dtype=float)
    if np.any(f <= 0) or center <= 0 or fractional_bw <= 0 or series_r < 0 or shunt_r <= 0 or z0 <= 0:
        raise ValueError("Positive frequencies/components and nonnegative loss are required.")
    w, w0 = 2 * np.pi * f, 2 * np.pi * center
    ls = z0 / (w0 * fractional_bw)
    cs = fractional_bw / (z0 * w0)
    cp = 2 / (z0 * w0 * fractional_bw)
    lp = z0 * fractional_bw / (2 * w0)
    z = series_r + 1j * (w * ls - 1 / (w * cs))
    y = 1 / shunt_r + 1j * (w * cp - 1 / (w * lp))
    # [1 Z; 0 1] @ [1 0; Y 1] @ [1 Z; 0 1]
    a, b, c, d = 1 + z * y, 2 * z + z * z * y, y, 1 + y * z
    denominator = a + b / z0 + c * z0 + d
    s = np.empty((len(f), 2, 2), dtype=complex)
    s[:, 0, 0] = (a + b / z0 - c * z0 - d) / denominator
    s[:, 1, 1] = (-a + b / z0 - c * z0 + d) / denominator
    s[:, 1, 0] = 2 / denominator
    # The reciprocal ladder has determinant AD-BC=1 exactly.
    s[:, 0, 1] = s[:, 1, 0]
    components = {"center_hz": center, "fractional_bw": fractional_bw, "z0_ohm": z0,
                  "series_L_H": ls, "series_C_F": cs, "shunt_L_H": lp, "shunt_C_F": cp,
                  "series_R_ohm_each": series_r, "shunt_R_ohm": shunt_r}
    return s, components


def touchstone_bytes(frequency, s, description):
    lines = ["! SYNTHETIC: ideal lumped LC ladder; not VNA measurements",
             f"! {description}", "! Frequency S11.re S11.im S21.re S21.im S12.re S12.im S22.re S22.im",
             "# GHz S RI R 50"]
    for f, matrix in zip(frequency, s):
        values = [f / 1e9]
        for i, j in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            values.extend([matrix[i, j].real, matrix[i, j].imag])
        lines.append(" ".join(f"{value:.12e}" for value in values))
    return ("\n".join(lines) + "\n").encode("ascii")


def generate(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    f = np.linspace(1.9e9, 3.1e9, 1201)
    cases = {"nominal": dict(center=2.45e9, series_r=1.6, shunt_r=2500.0),
             "degraded": dict(center=2.54e9, series_r=9.0, shunt_r=650.0)}
    manifest = {"provenance": "synthetic circuit simulation", "model": "third-order Butterworth LC band-pass ladder",
                "assumptions": "Ideal lumped components, equal 50-ohm ports; no parasitics, calibration or EM model.", "cases": {}}
    for name, parameters in cases.items():
        s, components = simulate(f, **parameters)
        filename = f"filter-{name}.s2p"
        (directory / filename).write_bytes(touchstone_bytes(f, s, f"{name}; center={parameters['center']/1e9:.3f} GHz"))
        manifest["cases"][name] = {"file": filename, "components": components}
    (directory / "model.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
