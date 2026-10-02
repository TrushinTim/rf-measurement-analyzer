"""Bounded reader for two-port Touchstone 1.0 S-parameter files.

Rows use the Touchstone order S11, S21, S12, S22 (not row-major order).
Unsupported versions and noise data fail explicitly rather than being guessed.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import numpy as np

MAX_BYTES = 2 * 1024 * 1024
MAX_POINTS = 20000
UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}


class TouchstoneError(ValueError):
    pass


@dataclass(frozen=True)
class Network:
    name: str
    frequency: np.ndarray
    s: np.ndarray
    reference: float
    representation: str
    unit: str
    sha256: str


def number(token: str, line: int) -> float:
    try:
        value = float(token)
    except ValueError:
        raise TouchstoneError(
            f"Строка {line}: ожидалось число, получено {token[:40]!r}."
        )
    if not np.isfinite(value):
        raise TouchstoneError(f"Строка {line}: NaN и бесконечные числа недопустимы.")
    return value


def options(tokens, line):
    unit, representation, reference = "GHZ", "MA", 50.0
    seen = set()
    i = 0
    while i < len(tokens):
        token = tokens[i].upper()
        if token in UNITS:
            category, unit = "unit", token
        elif token in {"RI", "MA", "DB"}:
            category, representation = "format", token
        elif token in {"S", "Z", "Y", "H", "G"}:
            category = "parameter"
            if token != "S":
                raise TouchstoneError(
                    "Поддерживаются только S-параметры. Экспортируй файл в формате S."
                )
        elif token == "R":
            category = "reference"
            i += 1
            if i == len(tokens):
                raise TouchstoneError("После R нужно указать сопротивление в омах.")
            reference = number(tokens[i], line)
            if reference <= 0:
                raise TouchstoneError(
                    "Опорное сопротивление должно быть положительным."
                )
        else:
            raise TouchstoneError(
                f"Строка {line}: неизвестная опция {token[:40]!r}. Поддерживается Touchstone 1.0."
            )
        if category in seen:
            raise TouchstoneError(f"Строка {line}: опция {category} указана дважды.")
        seen.add(category)
        i += 1
    return unit, representation, reference


def parse(raw: bytes, filename: str) -> Network:
    name = Path(filename.replace("\\", "/")).name[:160]
    if not name.lower().endswith(".s2p"):
        raise TouchstoneError("Нужен двухпортовый файл с расширением .s2p.")
    if len(raw) > MAX_BYTES:
        raise TouchstoneError("Файл больше 2 МиБ. Уменьши число точек при экспорте.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TouchstoneError("Файл должен быть текстовым ASCII или UTF-8.")
    header = None
    records, pending = [], []
    for line_no, original in enumerate(text.splitlines(), 1):
        line = original.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            raise TouchstoneError(
                "Touchstone 2.x пока не поддерживается. Экспортируй Touchstone 1.0 / S2P."
            )
        if line.startswith("#"):
            if header is not None:
                # The specification says subsequent option lines are ignored.
                continue
            if records or pending:
                raise TouchstoneError("Строка опций # должна находиться перед данными.")
            header = options(line[1:].split(), line_no)
            continue
        if header is None:
            raise TouchstoneError("Нет строки опций #. Пример: # GHz S RI R 50.")
        values = [number(token, line_no) for token in line.split()]
        if len(pending) + len(values) > 9:
            raise TouchstoneError(
                f"Строка {line_no}: для одной частоты нужны 9 чисел; перенос строки разрешён."
            )
        pending.extend(values)
        if len(pending) == 9:
            records.append(pending)
            pending = []
            if len(records) > MAX_POINTS:
                raise TouchstoneError(
                    f"Поддерживается не более {MAX_POINTS} частотных точек."
                )
    if pending:
        raise TouchstoneError(
            "Неполная частотная точка или блок шумовых параметров. Шумовые данные не поддерживаются."
        )
    if len(records) < 3:
        raise TouchstoneError("Нужно минимум 3 частотные точки.")
    unit, representation, reference = header
    data = np.asarray(records, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        frequency = data[:, 0] * UNITS[unit]
        pairs = data[:, 1:].reshape(-1, 4, 2)
        if representation == "RI":
            values = pairs[:, :, 0] + 1j * pairs[:, :, 1]
        else:
            magnitude = pairs[:, :, 0]
            if representation == "MA" and np.any(magnitude < 0):
                raise TouchstoneError(
                    "В формате MA модуль не может быть отрицательным."
                )
            if representation == "DB":
                magnitude = 10.0 ** (magnitude / 20.0)
            values = magnitude * np.exp(1j * np.deg2rad(pairs[:, :, 1]))
    if not np.all(np.isfinite(frequency)) or not np.all(np.isfinite(values)):
        raise TouchstoneError("Числа выходят за пределы поддерживаемого диапазона.")
    if (
        np.any(frequency < 1)
        or np.any(frequency > 1e15)
        or np.any(np.abs(values) > 1e100)
    ):
        raise TouchstoneError(
            "Числа вне рабочего диапазона: частота 1 Гц–1000 ТГц, модуль S ≤ 1e100."
        )
    if np.any(frequency <= 0) or np.any(np.diff(frequency) <= 0):
        raise TouchstoneError(
            "Частоты должны быть положительными и строго возрастать без повторов. Шумовые блоки не поддерживаются."
        )
    s = np.empty((len(records), 2, 2), dtype=complex)
    s[:, 0, 0], s[:, 1, 0] = values[:, 0], values[:, 1]
    s[:, 0, 1], s[:, 1, 1] = values[:, 2], values[:, 3]
    frequency.setflags(write=False)
    s.setflags(write=False)
    return Network(
        name,
        frequency,
        s,
        reference,
        representation,
        unit,
        hashlib.sha256(raw).hexdigest(),
    )
