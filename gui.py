import sys, struct, threading, queue, time, ctypes
from ctypes import wintypes
import serial, serial.tools.list_ports
from PySide6 import QtCore, QtWidgets

user32 = ctypes.windll.user32

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEMOUSE = 0

try:
    HRAWINPUT = wintypes.HRAWINPUT
except AttributeError:
    HRAWINPUT = wintypes.HANDLE

UINT = getattr(wintypes, 'UINT', ctypes.c_uint)

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ('dwType', wintypes.DWORD),
        ('dwSize', wintypes.DWORD),
        ('hDevice', wintypes.HANDLE),
        ('wParam', wintypes.WPARAM),
    ]

class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ('usFlags', wintypes.USHORT),
        ('ulButtons', wintypes.ULONG),
        ('usButtonFlags', wintypes.USHORT),
        ('usButtonData', wintypes.USHORT),
        ('ulRawButtons', wintypes.ULONG),
        ('lLastX', wintypes.LONG),
        ('lLastY', wintypes.LONG),
        ('ulExtraInfo', wintypes.ULONG),
    ]

class RAWINPUTUNION(ctypes.Union):
    _fields_ = [('mouse', RAWMOUSE)]

class RAWINPUT(ctypes.Structure):
    _fields_ = [('header', RAWINPUTHEADER),
                ('data', RAWINPUTUNION)]

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ('usUsagePage', wintypes.USHORT),
        ('usUsage', wintypes.USHORT),
        ('dwFlags', wintypes.DWORD),
        ('hwndTarget', wintypes.HWND),
    ]

GetRawInputData = user32.GetRawInputData
GetRawInputData.restype = UINT
GetRawInputData.argtypes = [
    HRAWINPUT, UINT, ctypes.c_void_p, ctypes.POINTER(UINT), UINT
]

RegisterRawInputDevices = user32.RegisterRawInputDevices
RegisterRawInputDevices.restype = wintypes.BOOL
RegisterRawInputDevices.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICE), UINT, UINT
]

class SerialSender(QtCore.QObject):
    connectedChanged = QtCore.Signal(bool)
    statsUpdated = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.ser = None
        self._q = queue.Queue(maxsize=4096)
        self._running = False
        self._writer = None

    def open(self, port:str, baud:int=1000000):
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
            try: self.ser.close()
            except: pass
        self.ser = None
        self.connectedChanged.emit(False)

    def send_delta(self, dx:int, dy:int):
        if not self._running or not self.ser: return
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

class RawInputFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, hwnd:int, on_delta):
        super().__init__()
        self.hwnd = hwnd
        self.on_delta = on_delta
        self._registered = False
        self.register()

    def register(self):
        if self._registered: return
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage = 0x02
        rid.dwFlags = RIDEV_INPUTSINK
        rid.hwndTarget = wintypes.HWND(self.hwnd)
        ok = RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
        self._registered = bool(ok)

    def nativeEventFilter(self, eventType, message):
        if eventType != b'windows_generic_MSG':
            return False, 0
        msg = ctypes.cast(message, ctypes.POINTER(wintypes.MSG)).contents
        if msg.message == WM_INPUT:
            self._handle_wm_input(msg.lParam)
        return False, 0

    def _handle_wm_input(self, lparam):
        size = UINT(0)
        GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buf = ctypes.create_string_buffer(size.value)
        got = GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))
        if got == 0 or got == 0xFFFFFFFF:
            return
        ri = RAWINPUT.from_buffer_copy(buf)
        if ri.header.dwType != RIM_TYPEMOUSE:
            return
        dx = int(ri.data.mouse.lLastX)
        dy = int(ri.data.mouse.lLastY)
        if dx or dy:
            self.on_delta(dx, dy)

DARK_QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 12px; }
QWidget { background: #101217; color: #e6e6e6; }
QPushButton { background: #1c1f27; border: 1px solid #2a2f3a; padding: 8px 12px; border-radius: 8px; }
QPushButton:hover { background: #242935; }
QPushButton:checked { background: #2e3646; border-color: #3c4558; }
QComboBox { background: #1c1f27; border: 1px solid #2a2f3a; padding: 6px; border-radius: 6px; }
QLabel { color: #e6e6e6; }
QGroupBox { border: 1px solid #2a2f3a; border-radius: 8px; margin-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 4px 8px; color: #a9b1c7; }
"""

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mouse forwarder - Fizo")
        self.setMinimumSize(520, 260)

        self.sender = SerialSender()
        self.sender.connectedChanged.connect(self.on_connected_changed)
        self.sender.statsUpdated.connect(self.on_stats)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        g1 = QtWidgets.QGroupBox("Arduino (programming port) connection")
        l1 = QtWidgets.QGridLayout(g1)
        self.portCombo = QtWidgets.QComboBox()
        self.refreshBtn = QtWidgets.QPushButton("Refresh")
        self.connectBtn = QtWidgets.QPushButton("Connect")
        self.connectBtn.setCheckable(True)
        self.statusLbl = QtWidgets.QLabel("Disconnected")
        l1.addWidget(QtWidgets.QLabel("COM Port:"), 0, 0)
        l1.addWidget(self.portCombo, 0, 1)
        l1.addWidget(self.refreshBtn, 0, 2)
        l1.addWidget(self.connectBtn, 1, 1)
        l1.addWidget(self.statusLbl, 1, 2, alignment=QtCore.Qt.AlignRight)

        g2 = QtWidgets.QGroupBox("Mouse forwarding")
        l2 = QtWidgets.QGridLayout(g2)
        self.toggleBtn = QtWidgets.QPushButton("Start Forwarding")
        self.toggleBtn.setCheckable(True)
        self.rateLbl = QtWidgets.QLabel("0 pkts/s")
        l2.addWidget(self.toggleBtn, 0, 0)
        l2.addWidget(self.rateLbl, 0, 1, alignment=QtCore.Qt.AlignRight)

        tips = QtWidgets.QLabel(
            "Wiring:\n"
            "• Programming port → this PC (serial control)\n"
            "• Native USB Port → second PC (HID mouse)\n"
            "Flash the provided Arduino sketch first."
        )
        tips.setStyleSheet("color:#a9b1c7;")
        tips.setWordWrap(True)

        layout.addWidget(g1)
        layout.addWidget(g2)
        layout.addWidget(tips)

        self.refreshBtn.clicked.connect(self.fill_ports)
        self.connectBtn.toggled.connect(self.on_connect_toggled)
        self.toggleBtn.toggled.connect(self.on_toggle_forwarding)

        self.forwarding = False
        self.filter = None

        self.fill_ports()

    def fill_ports(self):
        self.portCombo.clear()
        items = []
        for p in serial.tools.list_ports.comports():
            label = f"{p.device} — {p.description}"
            items.append((label, p.device))
        items.sort(key=lambda x: ("arduino" not in x[0].lower(), x[0].lower()))
        for label, dev in items:
            self.portCombo.addItem(label, dev)

    def on_connect_toggled(self, checked):
        if checked:
            port = self.portCombo.currentData()
            ok = self.sender.open(port, 1000000)
            if not ok:
                self.statusLbl.setText("Failed")
                self.connectBtn.setChecked(False)
                return
            self.statusLbl.setText(f"Connected @ 1,000,000")
            self.connectBtn.setText("Disconnect")
        else:
            self.sender.close()
            self.statusLbl.setText("Disconnected")
            self.connectBtn.setText("Connect")

    def on_connected_changed(self, ok:bool):
        self.connectBtn.setChecked(ok)
        self.statusLbl.setText("Connected" if ok else "Disconnected")

    def on_toggle_forwarding(self, enabled):
        self.forwarding = enabled
        self.toggleBtn.setText("Stop Forwarding" if enabled else "Start Forwarding")
        app = QtWidgets.QApplication.instance()
        if enabled:
            hwnd = int(self.winId())
            if not self.filter:
                self.filter = RawInputFilter(hwnd, self._on_delta)
                app.installNativeEventFilter(self.filter)
        else:
            if self.filter:
                app.removeNativeEventFilter(self.filter)
                self.filter = None

    def _on_delta(self, dx:int, dy:int):
        if self.forwarding and self.sender.ser:
            self.sender.send_delta(dx, dy)

    def on_stats(self, pps:int):
        self.rateLbl.setText(f"{pps} pkts/s")

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
