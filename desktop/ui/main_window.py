from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QSpinBox, QGroupBox,
    QStatusBar, QSplitter, QDockWidget, QTextEdit, QFrame,
)
from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer
from PySide6.QtGui import QTextCursor
import pyqtgraph as pg
from datetime import datetime

from core.device import Device
from core.measurement import Point, SweepResult
from ui.freq_widget import FreqWidget

LOG_MAX_LINES = 500
RECONNECT_INTERVAL_MS = 3000


class _Bridge(QObject):
    data_received = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pico Impedance Analyzer")
        self.resize(1200, 750)

        self._bridge = _Bridge()
        self._bridge.data_received.connect(self._on_data)
        self._device = Device(on_data=lambda d: self._bridge.data_received.emit(d))
        self._sweep: SweepResult | None = None
        self._sweep_point_count = 0
        self._connected = False

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(RECONNECT_INTERVAL_MS)
        self._reconnect_timer.timeout.connect(self._try_connect)

        self._build_ui()
        self._build_log_dock()

        # auto-connect po vykresleni okna
        QTimer.singleShot(300, self._try_connect)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        ctrl = QVBoxLayout()
        ctrl.setAlignment(Qt.AlignTop)
        ctrl.addWidget(self._build_status_bar())
        ctrl.addWidget(self._build_port_settings())
        ctrl.addWidget(self._build_sweep_group())
        ctrl.addWidget(self._build_single_group())
        ctrl.addStretch()

        left = QWidget()
        left.setFixedWidth(280)
        left.setLayout(ctrl)

        splitter = QSplitter(Qt.Vertical)
        self._plot_mag = pg.PlotWidget(title="Magnitude (dB)")
        self._plot_mag.setLabel("left", "dB")
        self._plot_mag.setLabel("bottom", "Frequency", units="Hz")
        self._plot_mag.showGrid(x=True, y=True)
        self._plot_mag.setYRange(0, 60, padding=0)
        self._curve_mag = self._plot_mag.plot(pen=pg.mkPen("c", width=2))

        self._plot_phs = pg.PlotWidget(title="Phase (°)")
        self._plot_phs.setLabel("left", "°")
        self._plot_phs.setLabel("bottom", "Frequency", units="Hz")
        self._plot_phs.showGrid(x=True, y=True)
        self._plot_phs.setYRange(0, 180, padding=0)
        self._curve_phs = self._plot_phs.plot(pen=pg.mkPen("y", width=2))

        splitter.addWidget(self._plot_mag)
        splitter.addWidget(self._plot_phs)
        splitter.setSizes([350, 350])

        root.addWidget(left)
        root.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Hledám zařízení...")

    def _build_status_bar(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 4, 6, 4)

        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(14)
        self._status_lbl = QLabel("Odpojeno")

        self._disconnect_btn = QPushButton("Odpojit")
        self._disconnect_btn.setFixedWidth(70)
        self._disconnect_btn.clicked.connect(self._manual_disconnect)
        self._disconnect_btn.setVisible(False)

        self._settings_btn = QPushButton("Port...")
        self._settings_btn.setFixedWidth(55)
        self._settings_btn.setCheckable(True)
        self._settings_btn.clicked.connect(self._toggle_port_settings)

        layout.addWidget(self._status_dot)
        layout.addWidget(self._status_lbl, stretch=1)
        layout.addWidget(self._disconnect_btn)
        layout.addWidget(self._settings_btn)
        self._set_connected_ui(False)
        return frame

    def _build_port_settings(self):
        self._port_settings = QWidget()
        self._port_settings.setVisible(False)
        layout = QHBoxLayout(self._port_settings)
        layout.setContentsMargins(0, 0, 0, 0)

        self._port_combo = QComboBox()
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(28)
        refresh_btn.clicked.connect(self._refresh_ports)

        layout.addWidget(self._port_combo, stretch=1)
        layout.addWidget(refresh_btn)
        self._refresh_ports()
        return self._port_settings

    def _build_log_dock(self):
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setLineWrapMode(QTextEdit.NoWrap)
        self._log_edit.setStyleSheet(
            "QTextEdit { background: #0d1117; color: #e6edf3; font-family: monospace; font-size: 11px; }"
        )

        clear_btn = QPushButton("Vymazat")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._log_edit.clear)

        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.addWidget(QLabel("Komunikace"))
        bar_layout.addStretch()
        bar_layout.addWidget(clear_btn)

        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(bar)
        vl.addWidget(self._log_edit)

        dock = QDockWidget("Log", self)
        dock.setWidget(container)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        dock.setMinimumHeight(140)

    def _build_sweep_group(self):
        grp = QGroupBox("Sweep")
        layout = QVBoxLayout(grp)

        self._sweep_start = FreqWidget(default_hz=100_000)
        self._sweep_stop  = FreqWidget(default_hz=10_000_000)

        self._sweep_steps = QSpinBox()
        self._sweep_steps.setRange(2, 2000)
        self._sweep_steps.setValue(200)

        self._sweep_dwell = QSpinBox()
        self._sweep_dwell.setRange(5, 5000)
        self._sweep_dwell.setValue(10)
        self._sweep_dwell.setSuffix(" ms")
        self._sweep_dwell.setToolTip(
            "Min 5 ms — ADS1115 @ 128 SPS přidá vždy ~16 ms/krok.\n"
            "LC s vysokým Q: doporučeno 20–100 ms."
        )

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

        self._freq_widget = FreqWidget(default_hz=1_000_000)
        layout.addWidget(QLabel("Frekvence"))
        layout.addWidget(self._freq_widget)

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
    # Connection helpers
    # ------------------------------------------------------------------
    def _set_connected_ui(self, connected: bool, port: str = ""):
        self._connected = connected
        if connected:
            self._status_dot.setStyleSheet("color: #3fb950")
            self._status_lbl.setText(port)
            self._disconnect_btn.setVisible(True)
            self._settings_btn.setVisible(False)
            self._port_settings.setVisible(False)
            self._settings_btn.setChecked(False)
        else:
            self._status_dot.setStyleSheet("color: #f85149")
            self._status_lbl.setText("Odpojeno")
            self._disconnect_btn.setVisible(False)
            self._settings_btn.setVisible(True)

        self._sweep_btn.setEnabled(connected)
        self._set_freq_btn.setEnabled(connected)
        self._measure_btn.setEnabled(connected)

    def _try_connect(self):
        if self._connected:
            return
        port = self._port_combo.currentText() if self._port_settings.isVisible() \
               else Device.autodetect_port()
        if not port:
            self.statusBar().showMessage("Zařízení nenalezeno, zkouším znovu...")
            self._reconnect_timer.start()
            return
        try:
            self._device.connect(port)
            self._set_connected_ui(True, port)
            self._reconnect_timer.stop()
            self.statusBar().showMessage(f"Připojeno: {port}")
            self._log(f"Připojeno: {port}", color="#58a6ff")
        except Exception as e:
            self.statusBar().showMessage(f"Chyba připojení: {e}")
            self._reconnect_timer.start()

    def _manual_disconnect(self):
        self._device.disconnect()
        self._set_connected_ui(False)
        self._reconnect_timer.stop()
        self.statusBar().showMessage("Odpojeno ručně")
        self._log("Odpojeno", color="#f85149")

    def _toggle_port_settings(self, checked: bool):
        self._port_settings.setVisible(checked)
        if checked:
            self._refresh_ports()

    def _refresh_ports(self):
        self._port_combo.clear()
        self._port_combo.addItems(Device.list_ports())
        best = Device.autodetect_port()
        if best:
            idx = self._port_combo.findText(best)
            if idx >= 0:
                self._port_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------
    def _log(self, text: str, color: str = "#e6edf3"):
        doc = self._log_edit.document()
        while doc.blockCount() > LOG_MAX_LINES:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            f'<span style="color:#555">[{ts}]</span> <span style="color:{color}">{text}</span><br>'
        )
        self._log_edit.setTextCursor(cursor)
        self._log_edit.ensureCursorVisible()

    def _log_tx(self, cmd: str):
        self._log(f"&gt; {cmd}", color="#3fb950")

    def _log_rx(self, text: str, color: str = "#e6edf3"):
        self._log(f"&lt; {text}", color=color)

    # ------------------------------------------------------------------
    # Measurement slots
    # ------------------------------------------------------------------
    def _start_sweep(self):
        self._sweep = SweepResult()
        self._sweep_point_count = 0
        steps    = self._sweep_steps.value()
        start_hz = self._sweep_start.hz()
        stop_hz  = self._sweep_stop.hz()
        dwell    = self._sweep_dwell.value()
        self._plot_mag.setXRange(start_hz, stop_hz, padding=0)
        self._plot_phs.setXRange(start_hz, stop_hz, padding=0)
        self._log_tx(f"SWEEP {start_hz} {stop_hz} {steps} {dwell}")
        self._device.sweep(start_hz, stop_hz, steps, dwell)
        self.statusBar().showMessage("Sweep probíhá...")

    def _set_freq(self):
        hz = self._freq_widget.hz()
        self._log_tx(f"FREQ {hz}")
        self._device.set_frequency(hz)

    def _single_measure(self):
        self._log_tx("MEASURE")
        self._device.measure()

    @Slot(dict)
    def _on_data(self, data: dict):
        if "error" in data:
            msg = data["error"]
            self.statusBar().showMessage(f"Chyba: {msg}")
            self._log_rx(f"CHYBA: {msg}", color="#f85149")
            if msg == "serial disconnected":
                self._set_connected_ui(False)
                self._log("Zařízení odpojeno, zkouším znovu...", color="#f85149")
                self._reconnect_timer.start()
            return

        if "ready" in data:
            self.statusBar().showMessage("Zařízení připraveno")
            self._log_rx(str(data), color="#58a6ff")
            return

        if "i2c_scan" in data:
            self._log_rx(str(data), color="#d2a8ff")
            return

        if "sweep_start" in data:
            self._log_rx(str(data), color="#e3b341")
            return

        if "sweep_done" in data:
            n = len(self._sweep.points) if self._sweep else 0
            self.statusBar().showMessage(f"Sweep hotov ({n} bodů)")
            self._log_rx(f"sweep_done — {n} bodů nasbíráno", color="#e3b341")
            if self._sweep and n > 0:
                self._curve_mag.setData(self._sweep.frequencies, self._sweep.magnitudes_db)
                self._curve_phs.setData(self._sweep.frequencies, self._sweep.phases_deg)
            self._sweep = None
            return

        if "freq" in data and "vmag" in data:
            p = Point(
                freq_hz=int(data["freq"]),
                vmag_v=float(data["vmag"]),
                vphs_v=float(data["vphs"]),
            )
            if self._sweep is not None:
                self._sweep.append(p)
                self._sweep_point_count += 1
                self._curve_mag.setData(self._sweep.frequencies, self._sweep.magnitudes_db)
                self._curve_phs.setData(self._sweep.frequencies, self._sweep.phases_deg)
                total = self._sweep_steps.value() + 1
                self.statusBar().showMessage(f"Sweep: {self._sweep_point_count}/{total} bodů")
                if self._sweep_point_count % 10 == 0:
                    self._log_rx(
                        f"[{self._sweep_point_count}/{total}] {p.freq_hz} Hz  "
                        f"{p.magnitude_db:.1f} dB  {p.phase_deg:.1f}°",
                        color="#8b949e",
                    )
            else:
                self._result_lbl.setText(f"{p.magnitude_db:.1f} dB  /  {p.phase_deg:.1f}°")
                self._log_rx(f"{p.freq_hz} Hz  {p.magnitude_db:.1f} dB  {p.phase_deg:.1f}°")

        if "pong" in data:
            self._log_rx("pong", color="#58a6ff")
