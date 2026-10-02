"""Sample-based filter acceptance checks, with explicit coverage semantics."""

from typing import List, Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .touchstone import Network


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pass_start_ghz: float = Field(default=2.40, gt=0)
    pass_end_ghz: float = Field(default=2.50, gt=0)
    max_loss_db: float = Field(default=1.0, ge=0, le=100)
    min_return_loss_db: float = Field(default=20.0, ge=0, le=100)
    low_stop_start_ghz: float = Field(default=2.00, gt=0)
    low_stop_end_ghz: float = Field(default=2.15, gt=0)
    high_stop_start_ghz: float = Field(default=2.85, gt=0)
    high_stop_end_ghz: float = Field(default=3.05, gt=0)
    min_attenuation_db: float = Field(default=15.0, ge=0, le=150)

    @model_validator(mode="after")
    def ordered_bands(self):
        values = [
            self.low_stop_start_ghz,
            self.low_stop_end_ghz,
            self.pass_start_ghz,
            self.pass_end_ghz,
            self.high_stop_start_ghz,
            self.high_stop_end_ghz,
        ]
        if any(right <= left for left, right in zip(values, values[1:])):
            raise ValueError(
                "Полосы должны идти по порядку: нижняя полоса подавления → полоса пропускания → верхняя полоса подавления; границы строго возрастают."
            )
        return self


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_ids: List[str] = Field(min_length=1, max_length=2)
    requirements: Requirements = Field(default_factory=Requirements)


def magnitude_db(values):
    # Exact zeros are displayed as a floor, not exported as JSON infinity.
    return 20 * np.log10(np.maximum(np.abs(values), 1e-15))


def band_values(f, values, start, end):
    """Native samples plus interpolated boundaries, never extrapolation.

    At least 3 native samples must lie inside the requested band.
    This is NOT a guarantee between measured frequency points.
    """
    mask = (f >= start) & (f <= end)
    count = int(mask.sum())
    if f[0] > start or f[-1] < end:
        return None, None, count, "Файл не покрывает всю заданную полосу."
    if count < 3:
        return None, None, count, "В полосе меньше трёх исходных частотных точек."
    x = np.unique(np.concatenate(([start], f[mask], [end])))
    y = np.interp(x, f, values)
    return x, y, count, None


def requirement_check(code, label, f, values, start, end, limit, sense):
    x, y, count, reason = band_values(f, values, start, end)
    base = {
        "code": code,
        "label": label,
        "start_ghz": start,
        "end_ghz": end,
        "limit": limit,
        "sense": sense,
        "native_points": count,
    }
    if reason:
        return {
            **base,
            "status": "NOT_EVALUATED",
            "reason": reason,
            "actual": None,
            "margin_db": None,
            "worst_frequency_ghz": None,
        }
    index = int(np.argmax(y) if sense == "max" else np.argmin(y))
    actual = float(y[index])
    margin = limit - actual if sense == "max" else actual - limit
    return {
        **base,
        "status": "PASS" if margin >= 0 else "FAIL",
        "reason": None,
        "actual": actual,
        "margin_db": float(margin),
        "worst_frequency_ghz": float(x[index]),
    }


def bandwidth(f, transmission):
    """Connected -3 dB interval around the global sampled S21 maximum."""
    peak = int(np.argmax(transmission))
    level = transmission[peak] - 3.0
    left, right = peak, peak
    while left > 0 and transmission[left - 1] >= level:
        left -= 1
    while right < len(f) - 1 and transmission[right + 1] >= level:
        right += 1
    if left == 0 or right == len(f) - 1:
        return {
            "width_mhz": None,
            "lower_ghz": None,
            "upper_ghz": None,
            "reason": "Одна или обе границы −3 дБ находятся за пределами файла.",
        }
    lower = float(
        np.interp(level, transmission[left - 1 : left + 1], f[left - 1 : left + 1])
    )
    upper = float(
        np.interp(
            level, transmission[right : right + 2][::-1], f[right : right + 2][::-1]
        )
    )
    return {
        "width_mhz": (upper - lower) * 1000,
        "lower_ghz": lower,
        "upper_ghz": upper,
        "reason": None,
    }


def analyze(network: Network, req: Requirements, provenance="uploaded"):
    f = network.frequency / 1e9
    db = magnitude_db(network.s)
    s21 = db[:, 1, 0]
    loss = -s21
    # Both ports must satisfy the return loss requirement.
    return_loss = -np.maximum(db[:, 0, 0], db[:, 1, 1])
    checks = [
        requirement_check(
            "IL",
            "Потери в полосе · S21",
            f,
            loss,
            req.pass_start_ghz,
            req.pass_end_ghz,
            req.max_loss_db,
            "max",
        ),
        requirement_check(
            "RL",
            "Согласование обоих портов · S11 / S22",
            f,
            return_loss,
            req.pass_start_ghz,
            req.pass_end_ghz,
            req.min_return_loss_db,
            "min",
        ),
        requirement_check(
            "STOP-L",
            "Подавление ниже полосы",
            f,
            loss,
            req.low_stop_start_ghz,
            req.low_stop_end_ghz,
            req.min_attenuation_db,
            "min",
        ),
        requirement_check(
            "STOP-H",
            "Подавление выше полосы",
            f,
            loss,
            req.high_stop_start_ghz,
            req.high_stop_end_ghz,
            req.min_attenuation_db,
            "min",
        ),
    ]
    complete = all(check["status"] != "NOT_EVALUATED" for check in checks)
    # INCOMPLETE takes precedence, but individual confirmed FAILs remain visible.
    verdict = (
        "INCOMPLETE"
        if not complete
        else ("FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS")
    )
    peak = int(np.argmax(s21))
    # Unwrap contiguous valid segments independently: a phase at a zero/null
    # must not contaminate its valid neighbours or bridge a masked interval.
    valid_delay = s21 > -60
    delay_ns = np.full(len(f), np.nan)
    edges = np.diff(np.r_[False, valid_delay, False].astype(int))
    for start, stop in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
        if stop - start < 3:
            continue
        phase = np.unwrap(np.angle(network.s[start:stop, 1, 0]))
        delay_ns[start:stop] = (
            -np.gradient(phase, network.frequency[start:stop], edge_order=2)
            / (2 * np.pi)
            * 1e9
        )
    valid_delay &= np.isfinite(delay_ns)
    pass_mask = (f >= req.pass_start_ghz) & (f <= req.pass_end_ghz) & valid_delay
    delay_range = (
        [float(np.min(delay_ns[pass_mask])), float(np.max(delay_ns[pass_mask]))]
        if pass_mask.any()
        else None
    )
    warnings = []
    if np.max(np.linalg.svd(network.s, compute_uv=False)) > 1 + 1e-6:
        warnings.append(
            "Некоторые точки не соответствуют пассивной двухпортовой цепи. Проверь тип устройства и калибровку; это диагностический признак, а не отдельный критерий PASS/FAIL."
        )
    if np.max(np.abs(network.s[:, 0, 1] - network.s[:, 1, 0])) > 1e-5:
        warnings.append(
            "S12 и S21 различаются: устройство не выглядит взаимным на этой сетке."
        )
    max_step = float(np.max(np.diff(f)) * 1000)
    if max_step > 10:
        warnings.append(
            f"Максимальный шаг {max_step:.2f} МГц: узкие провалы между точками могут остаться незамеченными."
        )
    if np.any(np.abs(network.s) < 1e-15):
        warnings.append(
            "Нулевые или очень малые модули показаны с численным полом −300 дБ; значения ниже этого пола не различаются."
        )
    indices = np.unique(np.linspace(0, len(f) - 1, min(len(f), 2000), dtype=int))
    # Preserve worst points and global peak in a decimated display.
    extra = [peak] + [
        int(np.argmin(abs(f - c["worst_frequency_ghz"])))
        for c in checks
        if c["actual"] is not None
    ]
    indices = np.union1d(indices, extra).astype(int)
    series = {}
    for key, i, j in [("S11", 0, 0), ("S21", 1, 0), ("S12", 0, 1), ("S22", 1, 1)]:
        series[key] = db[indices, i, j].tolist()
    return {
        "name": network.name,
        "source": provenance,
        "sha256": network.sha256,
        "points": len(f),
        "reference_ohm": network.reference,
        "format": network.representation,
        "range_ghz": [float(f[0]), float(f[-1])],
        "max_step_mhz": max_step,
        "verdict": verdict,
        "checks": checks,
        "warnings": warnings,
        "peak_frequency_ghz": float(f[peak]),
        "peak_s21_db": float(s21[peak]),
        "bandwidth": bandwidth(f, s21),
        "delay_range_ns": delay_range,
        "plot": {
            "frequency_ghz": f[indices].tolist(),
            "db": series,
            "delay_ns": [
                float(delay_ns[i]) if valid_delay[i] else None for i in indices
            ],
        },
    }
