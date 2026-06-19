from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QSpinBox, QGroupBox,
    QStatusBar, QDoubleSpinBox, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QObject, Slot
import pyqtgraph as pg
import numpy as np

from core.device import Device
from core.measurement import Point, SweepResult


class _Bridge(QObject):
    data_received = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pico Impedance Analyzer")
        self.resize(1100, 700)

        self._bridge = _Bridge()
        self._bridge.data_received.connect(self._on_data)
        self._device = Device(on_data=lambda d: self._bridge.data_received.emit(d))
        self._sweep: SweepResult | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # Left panel — controls
        ctrl = QVBoxLayout()
        ctrl.setAlignment(Qt.AlignTop)
        ctrl.addWidget(self._build_connection_group())
        ctrl.addWidget(self._build_sweep_group())
        ctrl.addWidget(self._build_single_group())
        ctrl.addStretch()

        left = QWidget()
        left.setFixedWidth(280)
        left.setLayout(ctrl)

        # Right panel — plots
        splitter = QSplitter(Qt.Vertical)
        self._plot_mag = pg.PlotWidget(title="Magnitude (dB)")
        self._plot_mag.setLabel("left", "dB")
        self._plot_mag.setLabel("bottom", "Frequency", units="Hz")
        self._plot_mag.showGrid(x=True, y=True)
        self._curve_mag = self._plot_mag.plot(pen=pg.mkPen("c", width=2))

        self._plot_phs = pg.PlotWidget(title="Phase (°)")
        self._plot_phs.setLabel("left", "Degree")
        self._plot_phs.setLabel("bottom", "Frequency", units="Hz")
        self._plot_phs.showGrid(x=True, y=True)
        self._curve_phs = self._plot_phs.plot(pen=pg.mkPen("y", width=2))

        splitter.addWidget(self._plot_mag)
        splitter.addWidget(self._plot_phs)
        splitter.setSizes([350, 350])

        root.addWidget(left)
        root.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Odpojeno")

    def _build_connection_group(self):
        grp = QGroupBox("Připojení")
        layout = QVBoxLayout(grp)

        row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._refresh_btn = QPushButton("⟳")
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.clicked.connect(self._refresh_ports)
        row.addWidget(self._port_combo, stretch=1)
        row.addWidget(self._refresh_btn)
        layout.addLayout(row)

        self._connect_btn = QPushButton("Připojit")
        self._connect_btn.clicked.connect(self._toggle_connect)
        layout.addWidget(self._connect_btn)

        self._refresh_ports()
        return grp

    def _build_sweep_group(self):
        grp = QGroupBox("Sweep")
        layout = QVBoxLayout(grp)

        def hz_spin(default, max_val=70_000_000):
            w = QSpinBox()
            w.setRange(1, max_val)
            w.setValue(default)
            w.setSingleStep(10_000)
            w.setSuffix(" Hz")
            return w

        self._sweep_start = hz_spin(100_000)
        self._sweep_stop  = hz_spin(10_000_000)
        self._sweep_steps = QSpinBox()
        self._sweep_steps.setRange(2, 2000)
        self._sweep_steps.setValue(200)
        self._sweep_dwell = QSpinBox()
        self._sweep_dwell.setRange(1, 5000)
        self._sweep_dwell.setValue(5)
        self._sweep_dwell.setSuffix(" ms")

        layout.addWidget(QLabel("Start"))
        layout.addWidget(self._sweep_start)
        layout.addWidget(QLabel("Stop"))
        layout.addWidget(self._sweep_stop)
        layout.addWidget(QLabel("Kroků"))
        layout.addWidget(self._sweep_steps)
        layout.addWidget(QLabel("Prodleva"))
        layout.addWidget(self._sweep_dwell)

        self._sweep_btn = QPushButton("Spustit sweep")
        self._sweep_btn.clicked.connect(self._start_sweep)
        self._sweep_btn.setEnabled(False)
        layout.addWidget(self._sweep_btn)
        return grp

    def _build_single_group(self):
        grp = QGroupBox("Jednorázové měření")
        layout = QVBoxLayout(grp)

        self._freq_spin = QSpinBox()
        self._freq_spin.setRange(1, 70_000_000)
        self._freq_spin.setValue(1_000_000)
        self._freq_spin.setSuffix(" Hz")
        layout.addWidget(QLabel("Frekvence"))
        layout.addWidget(self._freq_spin)

        self._set_freq_btn = QPushButton("Nastavit frekvenci")
        self._set_freq_btn.clicked.connect(self._set_freq)
        self._set_freq_btn.setEnabled(False)
        layout.addWidget(self._set_freq_btn)

        self._measure_btn = QPushButton("Měřit")
        self._measure_btn.clicked.connect(self._single_measure)
        self._measure_btn.setEnabled(False)
        layout.addWidget(self._measure_btn)

        self._result_lbl = QLabel("—")
        self._result_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._result_lbl)
        return grp

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _refresh_ports(self):
        self._port_combo.clear()
        self._port_combo.addItems(Device.list_ports())

    def _toggle_connect(self):
        if self._connect_btn.text() == "Připojit":
            port = self._port_combo.currentText()
            if not port:
                return
            self._device.connect(port)
            self._connect_btn.setText("Odpojit")
            self._sweep_btn.setEnabled(True)
            self._set_freq_btn.setEnabled(True)
            self._measure_btn.setEnabled(True)
            self.statusBar().showMessage(f"Připojeno: {port}")
        else:
            self._device.disconnect()
            self._connect_btn.setText("Připojit")
            self._sweep_btn.setEnabled(False)
            self._set_freq_btn.setEnabled(False)
            self._measure_btn.setEnabled(False)
            self.statusBar().showMessage("Odpojeno")

    def _start_sweep(self):
        self._sweep = SweepResult()
        self._device.sweep(
            self._sweep_start.value(),
            self._sweep_stop.value(),
            self._sweep_steps.value(),
            self._sweep_dwell.value(),
        )
        self.statusBar().showMessage("Sweep probíhá...")

    def _set_freq(self):
        self._device.set_frequency(self._freq_spin.value())

    def _single_measure(self):
        self._device.measure()

    @Slot(dict)
    def _on_data(self, data: dict):
        if "error" in data:
            self.statusBar().showMessage(f"Chyba: {data['error']}")
            return
        if "ready" in data:
            self.statusBar().showMessage("Zařízení připraveno")
            return
        if "sweep_done" in data:
            self.statusBar().showMessage(f"Sweep hotov ({len(self._sweep.points)} bodů)")
            return
        if "freq" in data and "vmag" in data:
            p = Point(
                freq_hz=int(data["freq"]),
                vmag_v=float(data["vmag"]),
                vphs_v=float(data["vphs"]),
            )
            if self._sweep is not None and not data.get("sweep_start"):
                self._sweep.append(p)
                freqs = self._sweep.frequencies
                self._curve_mag.setData(freqs, self._sweep.magnitudes_db)
                self._curve_phs.setData(freqs, self._sweep.phases_deg)
            else:
                self._result_lbl.setText(
                    f"{p.magnitude_db:.1f} dB  /  {p.phase_deg:.1f}°"
                )
