import numpy as np
from dataclasses import dataclass, field


# AD8302: VMAG 0–1.8 V → 0–60 dB (1 V = 30 dB, slope ~30 mV/dB)
AD8302_MAG_SLOPE_V_PER_DB = 0.030
AD8302_MAG_OFFSET_V = 0.0       # 0 V = 0 dB (adjust per board calibration)

# AD8302: VPHS 0–1.8 V → 0°–180°
AD8302_PHS_SLOPE_V_PER_DEG = 0.010  # 10 mV/deg
AD8302_PHS_OFFSET_V = 0.0


@dataclass
class Point:
    freq_hz: int
    vmag_v: float
    vphs_v: float

    @property
    def magnitude_db(self) -> float:
        return (self.vmag_v - AD8302_MAG_OFFSET_V) / AD8302_MAG_SLOPE_V_PER_DB

    @property
    def phase_deg(self) -> float:
        return (self.vphs_v - AD8302_PHS_OFFSET_V) / AD8302_PHS_SLOPE_V_PER_DEG


@dataclass
class SweepResult:
    points: list[Point] = field(default_factory=list)

    def append(self, p: Point) -> None:
        self.points.append(p)

    @property
    def frequencies(self) -> np.ndarray:
        return np.array([p.freq_hz for p in self.points])

    @property
    def magnitudes_db(self) -> np.ndarray:
        return np.array([p.magnitude_db for p in self.points])

    @property
    def phases_deg(self) -> np.ndarray:
        return np.array([p.phase_deg for p in self.points])
