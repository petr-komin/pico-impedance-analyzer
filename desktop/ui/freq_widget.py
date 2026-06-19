from PySide6.QtWidgets import QWidget, QHBoxLayout, QDoubleSpinBox, QComboBox

# AD9851 s 180 MHz krystalem (x6 PLL)
DDS_MAX_HZ = 70_000_000

_UNITS = {
    "Hz":  1,
    "kHz": 1_000,
    "MHz": 1_000_000,
}

_STEP = {
    "Hz":  1_000,
    "kHz": 1,
    "MHz": 0.1,
}

_DECIMALS = {
    "Hz":  0,
    "kHz": 3,
    "MHz": 6,
}


class FreqWidget(QWidget):
    """Frequency input: QDoubleSpinBox + Hz/kHz/MHz selector."""

    def __init__(self, default_hz: int = 1_000_000, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._spin = QDoubleSpinBox()
        self._spin.setDecimals(3)
        self._spin.setMinimum(0.001)

        self._unit = QComboBox()
        self._unit.addItems(list(_UNITS.keys()))
        self._unit.setFixedWidth(52)

        layout.addWidget(self._spin, stretch=1)
        layout.addWidget(self._unit)

        self._unit.setCurrentText("kHz")
        self._apply_unit("kHz")
        self.set_hz(default_hz)

        self._unit.currentTextChanged.connect(self._on_unit_changed)

    # ------------------------------------------------------------------
    def hz(self) -> int:
        mult = _UNITS[self._unit.currentText()]
        return max(1, min(DDS_MAX_HZ, round(self._spin.value() * mult)))

    def set_hz(self, value_hz: int):
        mult = _UNITS[self._unit.currentText()]
        self._spin.setValue(value_hz / mult)

    # ------------------------------------------------------------------
    def _apply_unit(self, unit: str):
        mult = _UNITS[unit]
        self._spin.setMaximum(DDS_MAX_HZ / mult)
        self._spin.setSingleStep(_STEP[unit])
        self._spin.setDecimals(_DECIMALS[unit])
        self._spin.setSuffix(f" {unit}")

    def _on_unit_changed(self, unit: str):
        hz = self.hz()           # uloz aktualni Hz hodnotu
        self._apply_unit(unit)
        self.set_hz(hz)          # prepocitej do nove jednotky
