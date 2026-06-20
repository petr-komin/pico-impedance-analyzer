from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QSpinBox, QDoubleSpinBox, QGroupBox,
    QStatusBar, QSplitter, QDockWidget, QTextEdit, QFrame, QCheckBox,
    QTabWidget, QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer
from PySide6.QtGui import QTextCursor
import pyqtgraph as pg
from datetime import datetime

from core.device import Device
from core.measurement import Point, SweepResult
from core import calibration as cal
from ui.freq_widget import FreqWidget

LOG_MAX_LINES = 500
RECONNECT_INTERVAL_MS = 3000

# Etalony SOL kalibrace
CAL_STANDARDS = ("short", "open", "load")
CAL_LABELS = {"short": "ZKRAT", "open": "NAPRÁZDNO", "load": "ZÁTĚŽ"}


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
        self._prev_freqs = None
        self._prev_mag   = None
        self._prev_phs   = None

        # konfigurace + kalibrace
        self._config = cal.AppConfig.load()
        self._cal = cal.Calibration.load()
        self._cal_capture: str | None = None        # probíhající záchyt etalonu
        self._cal_buffer: list[tuple[float, complex]] = []
        self._cal_pending: dict[int, dict[str, tuple[list, list]]] = {}

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

        tabs = QTabWidget()
        tabs.addTab(self._build_measure_tab(), "Měření")
        tabs.addTab(self._build_calib_tab(), "Kalibrace")
        ctrl.addWidget(tabs)
        ctrl.addStretch()

        left = QWidget()
        left.setFixedWidth(300)
        left.setLayout(ctrl)

        splitter = QSplitter(Qt.Vertical)
        self._plot_mag = pg.PlotWidget(title="Magnitude (dB)")
        self._plot_mag.setLabel("left", "dB")
        self._plot_mag.setLabel("bottom", "Frequency", units="Hz")
        self._plot_mag.showGrid(x=True, y=True)
        self._plot_mag.setYRange(0, 60, padding=0)
        self._curve_mag_ghost = self._plot_mag.plot(pen=pg.mkPen((0, 180, 180, 140), width=1))
        self._curve_mag       = self._plot_mag.plot(pen=pg.mkPen("c", width=2))

        self._plot_phs = pg.PlotWidget(title="Phase (°)")
        self._plot_phs.setLabel("left", "°")
        self._plot_phs.setLabel("bottom", "Frequency", units="Hz")
        self._plot_phs.showGrid(x=True, y=True)
        self._plot_phs.setYRange(0, 180, padding=0)
        self._curve_phs_ghost = self._plot_phs.plot(pen=pg.mkPen((220, 180, 0, 140), width=1))
        self._curve_phs       = self._plot_phs.plot(pen=pg.mkPen("y", width=2))

        splitter.addWidget(self._plot_mag)
        splitter.addWidget(self._plot_phs)
        splitter.setSizes([350, 350])

        root.addWidget(left)
        root.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Hledám zařízení...")
        self._set_connected_ui(False)  # vsechny widgety uz existuji

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
        # nezavolame _set_connected_ui zde — _sweep_btn jeste neexistuje
        self._status_dot.setStyleSheet("color: #f85149")
        self._disconnect_btn.setVisible(False)
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

        menu = self.menuBar().addMenu("Zobrazení")
        menu.addAction(dock.toggleViewAction())

    # ------------------------------------------------------------------
    # Záložka Měření
    # ------------------------------------------------------------------
    def _build_measure_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self._build_range_group())
        layout.addWidget(self._build_sweep_group())
        layout.addWidget(self._build_single_group())
        layout.addStretch()
        return tab

    def _build_range_group(self):
        grp = QGroupBox("Rozsah a režim")
        form = QFormLayout(grp)

        self._range_combo = QComboBox()
        self._range_combo.currentIndexChanged.connect(self._on_range_changed)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["C — kondenzátor", "L — cívka"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        form.addRow("Rozsah Rref", self._range_combo)
        form.addRow("Režim", self._mode_combo)
        self._refresh_range_combos()
        self._mode_combo.setCurrentIndex(0 if self._config.mode == "C" else 1)
        return grp

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

        self._repeat_chk = QCheckBox("Opakovat")
        self._repeat_chk.setToolTip("Po dokončení sweepnu spustí další automaticky")

        row = QHBoxLayout()
        self._sweep_btn = QPushButton("Spustit sweep")
        self._sweep_btn.clicked.connect(self._start_sweep)
        self._sweep_btn.setEnabled(False)
        row.addWidget(self._sweep_btn, stretch=1)
        row.addWidget(self._repeat_chk)
        layout.addLayout(row)
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

        self._lc_lbl = QLabel("—")
        self._lc_lbl.setAlignment(Qt.AlignCenter)
        self._lc_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(self._lc_lbl)
        return grp

    # ------------------------------------------------------------------
    # Záložka Kalibrace
    # ------------------------------------------------------------------
    def _build_calib_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 4, 0, 0)

        intro = QLabel(
            "<b>SOL kalibrace</b> (per rozsah). Nejprve nastav parametry sweepnu "
            "v záložce <i>Měření</i> — kalibrace použije stejný frekvenční rozsah.<br><br>"
            "Pro vybraný rozsah postupně připoj 3 etalony a změř je:<br>"
            "1. <b>ZKRAT</b> — propojené svorky (Z = 0)<br>"
            "2. <b>NAPRÁZDNO</b> — rozpojené svorky (Z = ∞)<br>"
            "3. <b>ZÁTĚŽ</b> — známý rezistor (zadej hodnotu níže)<br><br>"
            "Pak ulož. Parazitika relé/přípravku se vykrátí."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # výběr rozsahu
        grp = QGroupBox("Kalibrace rozsahu")
        gl = QFormLayout(grp)
        self._cal_range_combo = QComboBox()
        self._cal_range_combo.currentIndexChanged.connect(self._on_cal_range_changed)
        gl.addRow("Rozsah", self._cal_range_combo)

        self._cal_load_spin = QDoubleSpinBox()
        self._cal_load_spin.setRange(0.1, 100000.0)
        self._cal_load_spin.setDecimals(2)
        self._cal_load_spin.setSuffix(" Ω")
        self._cal_load_spin.setValue(self._config.load_standard_ohm)
        gl.addRow("Hodnota zátěže", self._cal_load_spin)
        layout.addWidget(grp)

        # tlačítka etalonů
        self._cal_btns: dict[str, QPushButton] = {}
        self._cal_status: dict[str, QLabel] = {}
        for std in CAL_STANDARDS:
            row = QHBoxLayout()
            btn = QPushButton(f"Změřit {CAL_LABELS[std]}")
            btn.clicked.connect(lambda _=False, s=std: self._cal_capture_start(s))
            btn.setEnabled(False)
            status = QLabel("—")
            status.setFixedWidth(20)
            status.setAlignment(Qt.AlignCenter)
            row.addWidget(btn, stretch=1)
            row.addWidget(status)
            layout.addLayout(row)
            self._cal_btns[std] = btn
            self._cal_status[std] = status

        self._cal_save_btn = QPushButton("Uložit kalibraci")
        self._cal_save_btn.clicked.connect(self._cal_save)
        layout.addWidget(self._cal_save_btn)

        self._cal_date_lbl = QLabel("")
        self._cal_date_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._cal_date_lbl.setWordWrap(True)
        layout.addWidget(self._cal_date_lbl)

        layout.addWidget(self._build_settings_group())
        layout.addStretch()

        self._on_cal_range_changed(0)
        return tab

    def _build_settings_group(self):
        grp = QGroupBox("Nastavení rozsahů (Rref)")
        form = QFormLayout(grp)

        self._rref_spins: list[QDoubleSpinBox] = []
        for i in range(3):
            spin = QDoubleSpinBox()
            spin.setRange(0.1, 1_000_000.0)
            spin.setDecimals(1)
            spin.setSuffix(" Ω")
            spin.setValue(self._config.rref[i])
            form.addRow(f"Rozsah {i + 1}", spin)
            self._rref_spins.append(spin)

        save_btn = QPushButton("Uložit nastavení")
        save_btn.clicked.connect(self._save_settings)
        form.addRow(save_btn)
        return grp

    # ------------------------------------------------------------------
    # Konfigurace / rozsahy
    # ------------------------------------------------------------------
    def _refresh_range_combos(self):
        labels = [self._config.range_label(i) for i in range(3)]
        for combo, attr in ((getattr(self, "_range_combo", None), "active_range"),
                            (getattr(self, "_cal_range_combo", None), None)):
            if combo is None:
                continue
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(labels)
            combo.blockSignals(False)
        if hasattr(self, "_range_combo"):
            self._range_combo.setCurrentIndex(self._config.active_range)

    def _on_range_changed(self, idx: int):
        # Sepne relé zvoleného rozsahu (Rref) a vybere kalibraci pro přepočet.
        self._config.active_range = idx
        self._config.save()
        if self._connected:
            self._device.set_range(idx)
            self._log_tx(f"RANGE {idx}")

    def _on_mode_changed(self, idx: int):
        self._config.mode = "C" if idx == 0 else "L"
        self._config.save()

    def _on_cal_range_changed(self, idx: int):
        date = self._cal.date(idx)
        if date:
            self._cal_date_lbl.setText(f"Uložená kalibrace: {date}")
        else:
            self._cal_date_lbl.setText("Rozsah zatím nekalibrován.")
        # obnov stav tlačítek dle rozpracovaných záchytů
        pend = self._cal_pending.get(idx, {})
        for std in CAL_STANDARDS:
            self._cal_status[std].setText("✓" if std in pend else "—")
            self._cal_status[std].setStyleSheet(
                "color: #3fb950;" if std in pend else "color: #8b949e;"
            )

    def _save_settings(self):
        for i, spin in enumerate(self._rref_spins):
            self._config.rref[i] = spin.value()
        self._config.save()
        self._refresh_range_combos()
        self.statusBar().showMessage("Nastavení uloženo")
        self._log("Nastavení rozsahů uloženo", color="#58a6ff")

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
        for btn in self._cal_btns.values():
            btn.setEnabled(connected)

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
            # sepni relé naposledy zvoleného rozsahu
            self._device.set_range(self._config.active_range)
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
    # Měření L/C
    # ------------------------------------------------------------------
    def _compute_lc(self, p: Point) -> cal.LCResult:
        idx = self._config.active_range
        return cal.compute_lc(
            p.vmag_v, p.vref_v, p.vphs_v, p.freq_hz,
            rref=self._config.rref[idx],
            mode=self._config.mode,
            cal=self._cal.get(idx),
        )

    def _show_lc(self, p: Point):
        r = self._compute_lc(p)
        z = r.z
        if r.mode == "L":
            qd = f"Q={r.q:.1f}" if r.q != float("inf") else "Q=∞"
        else:
            qd = f"D={r.d:.4f}" if r.d != float("inf") else "D=∞"
        self._lc_lbl.setText(
            f"{r.value_str()}   |   {qd}   |   ESR={r.esr:.2f} Ω"
        )

    # ------------------------------------------------------------------
    # Kalibrace — záchyt etalonů
    # ------------------------------------------------------------------
    def _cal_capture_start(self, standard: str):
        if not self._connected or self._cal_capture is not None:
            return
        self._cal_capture = standard
        self._cal_buffer = []
        steps    = self._sweep_steps.value()
        start_hz = self._sweep_start.hz()
        stop_hz  = self._sweep_stop.hz()
        dwell    = self._sweep_dwell.value()
        # sepni relé kalibrovaného rozsahu
        self._device.set_range(self._cal_range_combo.currentIndex())
        self._log_tx(f"[KAL {CAL_LABELS[standard]}] SWEEP {start_hz} {stop_hz} {steps} {dwell}")
        self._device.sweep(start_hz, stop_hz, steps, dwell)
        self.statusBar().showMessage(f"Kalibrace: měřím {CAL_LABELS[standard]}...")

    def _cal_capture_done(self):
        std = self._cal_capture
        self._cal_capture = None
        if not self._cal_buffer:
            self.statusBar().showMessage("Kalibrace: žádná data")
            return
        idx = self._cal_range_combo.currentIndex()
        freqs = [f for f, _ in self._cal_buffer]
        hs    = [h for _, h in self._cal_buffer]
        self._cal_pending.setdefault(idx, {})[std] = (freqs, hs)
        self._cal_status[std].setText("✓")
        self._cal_status[std].setStyleSheet("color: #3fb950;")
        self.statusBar().showMessage(
            f"Kalibrace: {CAL_LABELS[std]} zachyceno ({len(freqs)} bodů)"
        )
        self._log_rx(f"[KAL {CAL_LABELS[std]}] {len(freqs)} bodů", color="#e3b341")

    def _cal_save(self):
        idx = self._cal_range_combo.currentIndex()
        pend = self._cal_pending.get(idx, {})
        missing = [CAL_LABELS[s] for s in CAL_STANDARDS if s not in pend]
        if missing:
            self.statusBar().showMessage("Chybí etalony: " + ", ".join(missing))
            return
        # všechny tři sdílí stejnou frekvenční mřížku (stejný sweep)
        freqs = pend["short"][0]
        self._cal.set_range(
            idx,
            freqs=freqs,
            h_short=pend["short"][1],
            h_open=pend["open"][1],
            h_load=pend["load"][1],
            load_r=self._cal_load_spin.value(),
        )
        self._config.load_standard_ohm = self._cal_load_spin.value()
        self._config.save()
        self._cal.save()
        self._on_cal_range_changed(idx)
        self.statusBar().showMessage(
            f"Kalibrace rozsahu {idx + 1} uložena ({len(freqs)} bodů)"
        )
        self._log(f"Kalibrace rozsahu {idx + 1} uložena", color="#58a6ff")

    # ------------------------------------------------------------------
    # Measurement slots
    # ------------------------------------------------------------------
    def _start_sweep(self):
        # uloz stara data pro postupne mazani ghostu
        old_x, old_y = self._curve_mag.getData()
        if old_x is not None and len(old_x) > 0:
            self._prev_freqs = old_x
            self._prev_mag   = old_y
            _, old_y_phs = self._curve_phs.getData()
            self._prev_phs = old_y_phs
            self._curve_mag_ghost.setData(old_x, old_y)
            self._curve_phs_ghost.setData(old_x, old_y_phs)
        else:
            self._prev_freqs = self._prev_mag = self._prev_phs = None
        self._curve_mag.setData([], [])
        self._curve_phs.setData([], [])

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
            if self._cal_capture is not None:
                self._cal_capture_done()
                return
            n = len(self._sweep.points) if self._sweep else 0
            self._log_rx(f"sweep_done — {n} bodů", color="#e3b341")
            if self._sweep and n > 0:
                self._curve_mag.setData(self._sweep.frequencies, self._sweep.magnitudes_db)
                self._curve_phs.setData(self._sweep.frequencies, self._sweep.phases_deg)
                self._curve_mag_ghost.setData([], [])
                self._curve_phs_ghost.setData([], [])
            self._sweep = None
            if self._repeat_chk.isChecked():
                self._start_sweep()
            else:
                self.statusBar().showMessage(f"Sweep hotov ({n} bodů)")
            return

        if "freq" in data and "vmag" in data:
            p = Point(
                freq_hz=int(data["freq"]),
                vmag_v=float(data["vmag"]),
                vref_v=float(data["vref"]),
                vphs_v=float(data["vphs"]),
            )
            # záchyt kalibračního etalonu — nezasahuj do grafů
            if self._cal_capture is not None:
                h = cal.reconstruct_h(p.vmag_v, p.vref_v, p.vphs_v, sign=+1)
                self._cal_buffer.append((float(p.freq_hz), h))
                self.statusBar().showMessage(
                    f"Kalibrace {CAL_LABELS[self._cal_capture]}: {len(self._cal_buffer)} bodů"
                )
                return

            if self._sweep is not None:
                self._sweep.append(p)
                self._sweep_point_count += 1
                self._curve_mag.setData(self._sweep.frequencies, self._sweep.magnitudes_db)
                self._curve_phs.setData(self._sweep.frequencies, self._sweep.phases_deg)
                self._show_lc(p)
                # ghost orizni od aktualniho indexu dopredu
                if self._prev_freqs is not None:
                    i = self._sweep_point_count
                    if i < len(self._prev_freqs):
                        self._curve_mag_ghost.setData(self._prev_freqs[i:], self._prev_mag[i:])
                        self._curve_phs_ghost.setData(self._prev_freqs[i:], self._prev_phs[i:])
                    else:
                        self._curve_mag_ghost.setData([], [])
                        self._curve_phs_ghost.setData([], [])
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
                self._show_lc(p)
                self._log_rx(f"{p.freq_hz} Hz  {p.magnitude_db:.1f} dB  {p.phase_deg:.1f}°")

        if "pong" in data:
            self._log_rx("pong", color="#58a6ff")
