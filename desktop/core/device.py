import json
import threading
import serial
import serial.tools.list_ports
from typing import Callable, Optional


class Device:
    """Serial communication with the RP2040 firmware."""

    def __init__(self, on_data: Callable[[dict], None]):
        self._on_data = on_data
        self._port: Optional[serial.Serial] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    @staticmethod
    def autodetect_port() -> Optional[str]:
        ports = list(serial.tools.list_ports.comports())
        # 1. Raspberry Pi VID (RP2040 USB CDC)
        for p in ports:
            if p.vid == 0x2E8A:
                return p.device
        # 2. First ttyACM* (Linux CDC device)
        for p in ports:
            if "ttyACM" in p.device:
                return p.device
        # 3. First available
        return ports[0].device if ports else None

    def connect(self, port: str, baud: int = 115200) -> None:
        self._port = serial.Serial(port, baud, timeout=1)
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._running = False
        if self._port and self._port.is_open:
            self._port.close()

    def send(self, cmd: str) -> None:
        if self._port and self._port.is_open:
            self._port.write((cmd.strip() + "\n").encode())

    def ping(self) -> None:
        self.send("PING")

    def set_frequency(self, freq_hz: int) -> None:
        self.send(f"FREQ {freq_hz}")

    def measure(self) -> None:
        self.send("MEASURE")

    def sweep(self, start_hz: int, stop_hz: int, steps: int, dwell_ms: int) -> None:
        self.send(f"SWEEP {start_hz} {stop_hz} {steps} {dwell_ms}")

    def set_gain(self, gain: int) -> None:
        self.send(f"GAIN {gain}")

    def set_range(self, range_idx: int) -> None:
        self.send(f"RANGE {range_idx}")

    def _reader(self) -> None:
        while self._running:
            try:
                line = self._port.readline().decode(errors="replace").strip()
                if line:
                    try:
                        data = json.loads(line)
                        self._on_data(data)
                    except json.JSONDecodeError:
                        self._on_data({"raw": line})
            except serial.SerialException:
                self._running = False
                self._on_data({"error": "serial disconnected"})
