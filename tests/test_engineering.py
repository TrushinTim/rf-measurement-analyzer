import numpy as np
import pytest
from pydantic import ValidationError
from app.analysis import Requirements, analyze, bandwidth, requirement_check
from app.circuit import simulate, touchstone_bytes
from app.touchstone import parse


def test_passive_reciprocal_ladder_and_analytic_center_loss():
    f = np.linspace(1e9, 4e9, 1001)
    s, _ = simulate(f)
    assert np.linalg.svd(s, compute_uv=False).max() <= 1 + 1e-12
    np.testing.assert_allclose(s[:, 0, 1], s[:, 1, 0])
    np.testing.assert_allclose(s[:, 0, 0], s[:, 1, 1])
    center, _ = simulate([2.45e9])
    r, g, z0 = 1.6, 1 / 2500, 50
    expected = 2 / (2 + 2 * r * g + (2 * r + r * r * g) / z0 + g * z0)
    assert center[0, 1, 0].real == pytest.approx(expected, abs=1e-12)
    assert abs(center[0, 1, 0].imag) < 1e-12


def test_lossless_ladder_conserves_power():
    s, _ = simulate(np.linspace(1.8e9, 3.2e9, 300), series_r=0, shunt_r=np.inf)
    identity = np.einsum("nji,njk->nik", s.conj(), s)
    np.testing.assert_allclose(
        identity, np.broadcast_to(np.eye(2), identity.shape), atol=1e-12
    )


def test_controlled_fault_changes_verdict_and_peak():
    f = np.linspace(1.9e9, 3.1e9, 1201)
    for params, verdict in [
        ({}, "PASS"),
        ({"center": 2.54e9, "series_r": 9, "shunt_r": 650}, "FAIL"),
    ]:
        s, _ = simulate(f, **params)
        result = analyze(
            parse(touchstone_bytes(f, s, "test"), "filter.s2p"), Requirements()
        )
        assert result["verdict"] == verdict
        assert result["peak_frequency_ghz"] == pytest.approx(
            params.get("center", 2.45e9) / 1e9
        )
        if verdict == "FAIL":
            assert [c["code"] for c in result["checks"] if c["status"] == "FAIL"] == [
                "IL",
                "RL",
                "STOP-H",
            ]


def test_group_delay_from_known_phase_slope():
    f = np.linspace(1.9e9, 3.1e9, 1201)
    s = np.zeros((len(f), 2, 2), complex)
    s[:, 0, 0] = 0.01
    s[:, 1, 1] = 0.005
    s[:, 1, 0] = 0.95 * np.exp(-1j * 2 * np.pi * f * 2.5e-9)
    s[:, 0, 1] = s[:, 1, 0]
    r = analyze(parse(touchstone_bytes(f, s, "delay"), "delay.s2p"), Requirements())
    np.testing.assert_allclose(r["delay_range_ns"], [2.5, 2.5], atol=1e-8)


def test_bandwidth_interpolation_and_truncated_band():
    f = np.arange(1, 8, dtype=float)
    r = bandwidth(f, np.array([-9, -6, -3, 0, -3, -6, -9]))
    assert r["width_mhz"] == 2000 and r["lower_ghz"] == 3 and r["upper_ghz"] == 5
    assert bandwidth(f, np.zeros(7))["width_mhz"] is None


@pytest.mark.parametrize(
    "sense,limit,values", [("max", 1, [0, 1, 0]), ("min", 20, [30, 20, 30])]
)
def test_inclusive_acceptance_and_signed_margin(sense, limit, values):
    f = np.array([2.4, 2.45, 2.5])
    values = np.array(values, float)
    r = requirement_check("X", "Test", f, values, 2.4, 2.5, limit, sense)
    assert r["status"] == "PASS" and r["margin_db"] == 0
    values[1] += 0.01 if sense == "max" else -0.01
    r = requirement_check("X", "Test", f, values, 2.4, 2.5, limit, sense)
    assert r["status"] == "FAIL" and r["margin_db"] == pytest.approx(-0.01)


def test_partial_coverage_and_sparse_band_are_not_pass():
    f = np.array([2.4, 2.45, 2.5]) * 1e9
    s, _ = simulate(f)
    r = analyze(parse(touchstone_bytes(f, s, "partial"), "partial.s2p"), Requirements())
    assert r["verdict"] == "INCOMPLETE"
    assert r["checks"][0]["status"] == "PASS"
    assert r["checks"][2]["status"] == "NOT_EVALUATED"
    c = requirement_check(
        "X", "Test", np.array([2.0, 2.3, 2.6, 3.1]), np.zeros(4), 2.4, 2.5, 1, "max"
    )
    assert c["status"] == "NOT_EVALUATED"


def test_interpolated_band_edges_are_included():
    c = requirement_check(
        "X",
        "Test",
        np.array([2.0, 2.3, 2.4, 2.45, 2.5, 2.6, 3.0]),
        np.array([0, 5, 0, 0, 0, 0, 0]),
        2.35,
        2.55,
        1,
        "max",
    )
    assert c["status"] == "FAIL" and c["actual"] == pytest.approx(2.5)


@pytest.mark.parametrize(
    "overrides",
    [
        {"pass_start_ghz": 2.6},
        {"max_loss_db": -1},
        {"pass_end_ghz": float("nan")},
        {"unexpected": 1},
        {"low_stop_end_ghz": 2.8},
    ],
)
def test_bad_requirements(overrides):
    with pytest.raises(ValidationError):
        Requirements(**overrides)


def test_output_port_return_loss_and_zero_transmission_mask():
    f = np.linspace(1.9e9, 3.1e9, 1201)
    s, _ = simulate(f)
    s[:, 0, 0] = 0.01
    s[:, 1, 1] = 0.3
    s[:5, 1, 0] = 0
    r = analyze(
        parse(touchstone_bytes(f, s, "output port"), "output.s2p"), Requirements()
    )
    assert r["checks"][1]["status"] == "FAIL"
    assert r["checks"][1]["actual"] == pytest.approx(-20 * np.log10(0.3))
    assert r["plot"]["delay_ns"][:5] == [None] * 5
