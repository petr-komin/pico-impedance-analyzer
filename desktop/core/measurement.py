import numpy as np
from dataclasses import dataclass, field

# AD8302: VMAG and VPHS are ratiometric to VREF (~1.8 V).
# VMAG: 0 V → 0 dB, VREF → 60 dB  (slope ~30 mV/dB)
# VPHS: 0 V → 0°,  VREF → 180°    (slope ~10 mV/°)


@dataclass
class Point:
    freq_hz: int
    vmag_v: float
    vref_v: float
    vphs_v: float

    @property
    def magnitude_db(self) -> float:
        if self.vref_v < 0.1:
            return 0.0
        return self.vmag_v / self.vref_v * 60.0

    @property
    def phase_deg(self) -> float:
        if self.vref_v < 0.1:
            return 0.0
        return self.vphs_v / self.vref_v * 180.0


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
