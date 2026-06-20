"""Konfigurace rozsahů + SOL kalibrace + přepočet napětí AD8302 na impedanci.

Měřicí přípravek: napěťový dělič se sériovým referenčním rezistorem.

    DDS ─►[buffer]──┬───[ Rref ]───┬─── DUT ─── GND
                  uzel A          uzel B
                  (INPA)          (INPB)

AD8302 vrací poměr |V_A/V_B| (z VMAG/VREF) a fázi (z VPHS/VREF).
Přenos děliče:  H = V_B / V_A = Z / (Rref + Z)   →   Z = Rref · H / (1 - H)

SOL kalibrace (per rozsah, per frekvence) vykrátí parazitní L/C relé,
rezistoru, vstupu AD8302 i přípravku pomocí 3 etalonů:
    ZKRAT (short, Z=0), NAPRÁZDNO (open, Z=∞), ZÁTĚŽ (load, Z=R).
Z naměřených H pro tyto etalony se sestaví bilineární (Möbiova) transformace
    Z(n) = a·(n - n_s) / (c·n + 1),   c = -1/n_o,   a = R·(c·n_l + 1)/(n_l - n_s)
která naměřené H mapuje na skutečnou Z.
"""

from __future__ import annotations

import cmath
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

# --- AD8302 transfer (ratiometrický vůči VREF, odolný vůči driftu napájení) ---
# VMAG: vmag/vref = 0.5 → 0 dB, = 1.0 → +30 dB, = 0.0 → -30 dB  (rozsah ±30 dB)
# VPHS: vphs/vref → |fáze| 0°–180°
_MAG_SPAN_DB = 60.0   # plný rozsah VREF odpovídá 60 dB (−30..+30)
_PHS_SPAN_DEG = 180.0

_BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = _BASE_DIR / "config.json"
CALIB_PATH = _BASE_DIR / "calibration.json"

DEFAULT_RREF = [51.0, 510.0, 5111.0]


# ----------------------------------------------------------------------
# Přepočet napětí AD8302 → naměřený komplexní poměr H = V_B / V_A
# ----------------------------------------------------------------------
def measured_ratio(vmag_v: float, vref_v: float, vphs_v: float) -> tuple[float, float]:
    """Vrátí (|V_A/V_B| lineárně, |fáze| ve stupních)."""
    if vref_v < 0.1:
        return 1.0, 0.0
    db = (vmag_v / vref_v - 0.5) * _MAG_SPAN_DB
    mag = 10.0 ** (db / 20.0)               # |V_A / V_B|
    phi = (vphs_v / vref_v) * _PHS_SPAN_DEG  # |arg|, 0..180°
    return mag, phi


def reconstruct_h(vmag_v: float, vref_v: float, vphs_v: float, sign: int = +1) -> complex:
    """Naměřené H = V_B / V_A jako komplexní číslo (fázový znak dle `sign`)."""
    mag, phi = measured_ratio(vmag_v, vref_v, vphs_v)
    h_mag = 1.0 / mag if mag > 1e-9 else 0.0   # |V_B/V_A|
    return h_mag * cmath.exp(1j * math.radians(sign * phi))


def _z_from_h_raw(h: complex, rref: float) -> complex:
    """Nekalibrovaný výpočet Z z přenosu děliče."""
    denom = 1.0 - h
    if abs(denom) < 1e-12:
        return complex(1e12, 0.0)
    return rref * h / denom


# ----------------------------------------------------------------------
# Konfigurace
# ----------------------------------------------------------------------
@dataclass
class AppConfig:
    rref: list[float] = field(default_factory=lambda: list(DEFAULT_RREF))
    load_standard_ohm: float = 50.0
    mode: str = "C"          # "L" nebo "C"
    active_range: int = 0

    def range_label(self, i: int) -> str:
        r = self.rref[i]
        if r >= 1000:
            return f"R{i + 1}: {r / 1000:g} kΩ"
        return f"R{i + 1}: {r:g} Ω"

    # --- perzistence ---
    @classmethod
    def load(cls) -> "AppConfig":
        if CONFIG_PATH.exists():
            try:
                d = json.loads(CONFIG_PATH.read_text())
                cfg = cls(
                    rref=[float(x) for x in d.get("rref", DEFAULT_RREF)][:3],
                    load_standard_ohm=float(d.get("load_standard_ohm", 50.0)),
                    mode=str(d.get("mode", "C")),
                    active_range=int(d.get("active_range", 0)),
                )
                while len(cfg.rref) < 3:
                    cfg.rref.append(DEFAULT_RREF[len(cfg.rref)])
                return cfg
            except (ValueError, json.JSONDecodeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps({
            "rref": self.rref,
            "load_standard_ohm": self.load_standard_ohm,
            "mode": self.mode,
            "active_range": self.active_range,
        }, indent=2, ensure_ascii=False))


# ----------------------------------------------------------------------
# Kalibrace
# ----------------------------------------------------------------------
@dataclass
class RangeCalibration:
    """SOL data pro jeden rozsah: naměřené H etalonů vs frekvence."""
    freqs: np.ndarray
    h_short: np.ndarray   # komplexní pole
    h_open: np.ndarray
    h_load: np.ndarray
    load_r: float
    date: str

    def _interp(self, arr: np.ndarray, freq: float) -> complex:
        re = float(np.interp(freq, self.freqs, arr.real))
        im = float(np.interp(freq, self.freqs, arr.imag))
        return complex(re, im)

    def solve_z(self, h_meas: complex, freq: float) -> complex:
        """Bilineární mapování naměřeného H → skutečná Z na dané frekvenci."""
        n_s = self._interp(self.h_short, freq)
        n_o = self._interp(self.h_open, freq)
        n_l = self._interp(self.h_load, freq)
        if abs(n_o) < 1e-12 or abs(n_l - n_s) < 1e-12:
            return complex(0.0, 0.0)
        c = -1.0 / n_o
        a = self.load_r * (c * n_l + 1.0) / (n_l - n_s)
        denom = c * h_meas + 1.0
        if abs(denom) < 1e-12:
            return complex(1e12, 0.0)
        return a * (h_meas - n_s) / denom


class Calibration:
    """Správa SOL kalibrace pro všechny rozsahy + perzistence."""

    def __init__(self) -> None:
        self._ranges: dict[int, RangeCalibration] = {}

    def has(self, range_idx: int) -> bool:
        return range_idx in self._ranges

    def date(self, range_idx: int) -> str | None:
        c = self._ranges.get(range_idx)
        return c.date if c else None

    def set_range(self, range_idx: int,
                  freqs, h_short, h_open, h_load, load_r: float) -> None:
        self._ranges[range_idx] = RangeCalibration(
            freqs=np.asarray(freqs, dtype=float),
            h_short=np.asarray(h_short, dtype=complex),
            h_open=np.asarray(h_open, dtype=complex),
            h_load=np.asarray(h_load, dtype=complex),
            load_r=float(load_r),
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    def get(self, range_idx: int) -> RangeCalibration | None:
        return self._ranges.get(range_idx)

    # --- perzistence ---
    @classmethod
    def load(cls) -> "Calibration":
        cal = cls()
        if not CALIB_PATH.exists():
            return cal
        try:
            d = json.loads(CALIB_PATH.read_text())
        except json.JSONDecodeError:
            return cal
        for key, r in d.get("ranges", {}).items():
            def _cx(name):
                return [complex(re, im) for re, im in r[name]]
            cal._ranges[int(key)] = RangeCalibration(
                freqs=np.asarray(r["freqs"], dtype=float),
                h_short=np.asarray(_cx("short"), dtype=complex),
                h_open=np.asarray(_cx("open"), dtype=complex),
                h_load=np.asarray(_cx("load"), dtype=complex),
                load_r=float(r["load_r"]),
                date=str(r.get("date", "")),
            )
        return cal

    def save(self) -> None:
        out = {"ranges": {}}
        for idx, c in self._ranges.items():
            out["ranges"][str(idx)] = {
                "date": c.date,
                "load_r": c.load_r,
                "freqs": c.freqs.tolist(),
                "short": [[z.real, z.imag] for z in c.h_short],
                "open": [[z.real, z.imag] for z in c.h_open],
                "load": [[z.real, z.imag] for z in c.h_load],
            }
        CALIB_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))


# ----------------------------------------------------------------------
# Výsledek měření L/C
# ----------------------------------------------------------------------
@dataclass
class LCResult:
    z: complex          # komplexní impedance [Ω]
    value: float        # L [H] nebo C [F] dle režimu
    esr: float          # sériový odpor Re(Z) [Ω]
    mode: str

    @property
    def reactance(self) -> float:
        return self.z.imag

    @property
    def q(self) -> float:
        """Činitel jakosti Q = |X| / ESR (cívka i kondenzátor)."""
        if self.esr <= 1e-9:
            return float("inf")
        return abs(self.reactance) / self.esr

    @property
    def d(self) -> float:
        """Ztrátový činitel D = 1/Q = ESR / |X| (ztrátový úhel)."""
        x = abs(self.reactance)
        if x < 1e-12:
            return float("inf")
        return self.esr / x

    def value_str(self) -> str:
        if self.mode == "L":
            return _eng(self.value, "H")
        return _eng(self.value, "F")


def compute_lc(vmag_v: float, vref_v: float, vphs_v: float,
               freq_hz: float, rref: float, mode: str,
               cal: RangeCalibration | None = None) -> LCResult:
    """Naměřená napětí → komplexní Z → hodnota L nebo C.

    Fázový znak AD8302 je nejednoznačný (vrací jen |fázi|), proto se vypočtou
    obě varianty a vybere se ta s reaktancí odpovídající zvolenému režimu
    (L → Im(Z) > 0, C → Im(Z) < 0).
    """
    candidates = []
    for sign in (+1, -1):
        h = reconstruct_h(vmag_v, vref_v, vphs_v, sign=sign)
        z = cal.solve_z(h, freq_hz) if cal is not None else _z_from_h_raw(h, rref)
        candidates.append(z)

    if mode == "L":
        z = max(candidates, key=lambda zz: zz.imag)
    else:
        z = min(candidates, key=lambda zz: zz.imag)

    w = 2.0 * math.pi * freq_hz
    x = z.imag
    if mode == "L":
        value = x / w if w > 0 else 0.0
    else:
        value = (-1.0 / (w * x)) if (w > 0 and abs(x) > 1e-12) else float("inf")
    return LCResult(z=z, value=value, esr=z.real, mode=mode)


def _eng(value: float, unit: str) -> str:
    """Formátování s inženýrskou předponou (p, n, µ, m, ...)."""
    if value == 0 or not math.isfinite(value):
        return f"— {unit}"
    prefixes = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"),
                (1.0, ""), (1e3, "k"), (1e6, "M")]
    av = abs(value)
    for scale, pref in prefixes:
        if av < scale * 1000:
            return f"{value / scale:.3g} {pref}{unit}"
    return f"{value:.3g} {unit}"
