from PySide6.QtWidgets import QWidget, QHBoxLayout, QDoubleSpinBox, QComboBox

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

        # ulozena Hz hodnota — aktualizuje se pri zmene spinboxu,
        # pouziva se pri zmene jednotky (combo uz ukazuje novou jednotku)
        self._hz = default_hz

        self._unit.setCurrentText("kHz")
        self._apply_unit("kHz")
        self._spin.setValue(default_hz / _UNITS["kHz"])

        self._spin.valueChanged.connect(self._on_value_changed)
        self._unit.currentTextChanged.connect(self._on_unit_changed)

    # ------------------------------------------------------------------
    def hz(self) -> int:
        return self._hz

    def set_hz(self, value_hz: int):
        self._hz = max(1, min(DDS_MAX_HZ, value_hz))
        mult = _UNITS[self._unit.currentText()]
        self._spin.blockSignals(True)
        self._spin.setValue(self._hz / mult)
        self._spin.blockSignals(False)

    # ------------------------------------------------------------------
    def _apply_unit(self, unit: str):
        mult = _UNITS[unit]
        self._spin.blockSignals(True)
        self._spin.setMaximum(DDS_MAX_HZ / mult)
        self._spin.setSingleStep(_STEP[unit])
        self._spin.setDecimals(_DECIMALS[unit])
        self._spin.setSuffix(f" {unit}")
        self._spin.blockSignals(False)

    def _on_value_changed(self, value: float):
        mult = _UNITS[self._unit.currentText()]
        self._hz = max(1, min(DDS_MAX_HZ, round(value * mult)))

    def _on_unit_changed(self, unit: str):
        # _hz je ulozena pred zmenou jednotky — pouzijeme ji primo
        saved_hz = self._hz
        self._apply_unit(unit)
        self.set_hz(saved_hz)
