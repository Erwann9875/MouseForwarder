import struct
import threading
import queue
import time
import serial
from PySide6 import QtCore

class SerialSender(QtCore.QObject):
    connectedChanged = QtCore.Signal(bool)
    statsUpdated = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.ser = None
        self._q = queue.Queue(maxsize=4096)
        self._running = False
        self._writer = None

    def open(self, port: str, baud: int = 1000000):
        self.close()
        try:
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=0, write_timeout=0)
            self._running = True
            self._writer = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer.start()
            self.connectedChanged.emit(True)
            return True
        except Exception:
            self.close()
            return False

    def close(self):
        self._running = False
        if self._writer and self._writer.is_alive():
            self._writer.join(timeout=0.2)
        self._writer = None
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connectedChanged.emit(False)

    def send_delta(self, dx: int, dy: int):
        if not self._running or not self.ser:
            return
        dx = 127 if dx > 127 else (-128 if dx < -128 else dx)
        dy = 127 if dy > 127 else (-128 if dy < -128 else dy)
        try:
            self._q.put_nowait(struct.pack('bb', dx, dy))
        except queue.Full:
            pass

    def _writer_loop(self):
        sent = 0
        last = time.time()
        while self._running and self.ser:
            try:
                pkt = self._q.get(timeout=0.01)
            except queue.Empty:
                now = time.time()
                if now - last >= 1.0:
                    self.statsUpdated.emit(sent)
                    sent = 0
                    last = now
                continue
            try:
                self.ser.write(pkt)
                sent += 1
            except Exception:
                self.close()
                break