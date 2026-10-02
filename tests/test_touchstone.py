import numpy as np
import pytest
from app.touchstone import MAX_BYTES, TouchstoneError, parse


def fixture(fmt="RI", unit="GHZ", reference=50):
    s = np.array([[.1+.2j, .7-.1j], [.8+.1j, -.2+.05j]])
    scale = {"HZ": 1e9, "KHZ": 1e6, "MHZ": 1e3, "GHZ": 1}[unit]
    rows = []
    for f in [2.4, 2.45, 2.5]:
        row = [f * scale]
        for i, j in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            value = s[i, j]
            if fmt == "RI": pair = [value.real, value.imag]
            else: pair = [abs(value) if fmt == "MA" else 20*np.log10(abs(value)), np.angle(value, deg=True)]
            row.extend(pair)
        rows.append(" ".join(map(str, row)))
    return (f"! independent nonreciprocal example\n# {unit} S {fmt} R {reference}\n" + "\n".join(rows)).encode(), s


@pytest.mark.parametrize("fmt", ["RI", "MA", "DB"])
@pytest.mark.parametrize("unit", ["HZ", "KHZ", "MHZ", "GHZ"])
def test_formats_units_and_port_order(fmt, unit):
    raw, expected = fixture(fmt, unit)
    n = parse(raw, "sample.s2p")
    np.testing.assert_allclose(n.s, np.broadcast_to(expected, (3, 2, 2)), atol=1e-14)
    np.testing.assert_allclose(n.frequency, [2.4e9, 2.45e9, 2.5e9])
    assert not n.s.flags.writeable


def test_wrapped_rows_comments_bom_and_option_order():
    raw, s = fixture()
    lines = raw.decode().splitlines()
    wrapped = ["\ufeff! UTF-8 comment: прибор", "# r 75 ri s GHz"]
    for row in lines[2:]:
        tokens = row.split()
        wrapped.extend([" ".join(tokens[:5]) + " ! inline", " ".join(tokens[5:])])
    n = parse("\n".join(wrapped).encode(), "../safe.s2p")
    assert n.name == "safe.s2p" and n.reference == 75
    np.testing.assert_allclose(n.s[0], s)


def test_default_options_and_subsequent_header_ignored():
    raw, s = fixture("MA")
    raw = raw.replace(b"# GHZ S MA R 50", b"#\n# Hz Z RI R 75")
    n = parse(raw, "SAMPLE.S2P")
    assert n.reference == 50 and n.unit == "GHZ"
    np.testing.assert_allclose(n.s[0], s)


@pytest.mark.parametrize("bad", [
    b"", b"# GHz S RI R 50\n1 0 0", b"[Version] 2.0\n# GHz S RI R 50",
    b"# GHz Z RI R 50", b"# GHz S RI R -1", b"# GHz S RI R",
    b"# GHz S RI R 50 75", b"# GHz S RI RI R 50", b"# nonsense",
    b"1 0 0 1 0 1 0 0 0", b"# GHz S RI R 50\nNaN 0 0 1 0 1 0 0 0",
    b"# GHz S RI R 50\n1 inf 0 1 0 1 0 0 0", b"\xff\xfe"
])
def test_malformed_is_rejected(bad):
    with pytest.raises(TouchstoneError): parse(bad, "bad.s2p")


def test_duplicate_or_reversed_frequencies_rejected():
    raw, _ = fixture()
    for f in [b"2.4", b"2.3"]:
        with pytest.raises(TouchstoneError, match="возрастать"):
            parse(raw.replace(b"2.45", f), "bad.s2p")


def test_noise_block_and_oversize_and_wrong_extension():
    raw, _ = fixture()
    with pytest.raises(TouchstoneError): parse(raw + b"\n1 0.7 0.64 69 0.38", "noise.s2p")
    with pytest.raises(TouchstoneError): parse(b"!"*(MAX_BYTES+1), "big.s2p")
    with pytest.raises(TouchstoneError): parse(raw, "bad.s1p")


def test_negative_magnitude_and_db_overflow():
    raw, _ = fixture("MA")
    lines = raw.decode().splitlines(); fields = lines[2].split(); fields[1] = "-1"
    lines[2] = " ".join(fields)
    with pytest.raises(TouchstoneError): parse("\n".join(lines).encode(), "negative.s2p")
    raw, _ = fixture("DB")
    lines = raw.decode().splitlines(); fields = lines[2].split(); fields[1] = "1e308"
    lines[2] = " ".join(fields)
    with pytest.raises(TouchstoneError): parse("\n".join(lines).encode(), "overflow.s2p")
