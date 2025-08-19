import sys, struct, threading, queue, time, ctypes, subprocess, os, shutil, json, re, tarfile, urllib.request
from ctypes import wintypes
import serial, serial.tools.list_ports
from PySide6 import QtCore, QtWidgets

if sys.platform != "win32":
    raise SystemExit("This app supports Windows only.")

def _detect_forbidden_processes() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist"], creationflags=0x08000000, stderr=subprocess.DEVNULL
        ).decode().lower()
        for name in (
            "cheatengine",
            "x64dbg",
            "ollydbg",
            "ida",
            "ghidra",
            "windbg",
            "immunitydebugger",
            "processhacker",
            "procexp",
            "frida",
            "gdb",
            "radare",
        ):
            if name in out:
                return True
    except Exception:
        pass
    return False

def _detect_suspicious_windows() -> bool:
    try:
        user32 = ctypes.windll.user32
        titles = []
        suspicious = (
            "cheat engine",
            "x64dbg",
            "ollydbg",
            "ida",
            "windbg",
            "immunity debugger",
            "process hacker",
            "process explorer",
            "frida",
            "ghidra",
        )

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.lower()
            for name in suspicious:
                if name in title:
                    titles.append(title)
                    return False
            return True

        user32.EnumWindows(enum_cb, 0)
        return bool(titles)
    except Exception:
        return False

def _detect_suspicious_modules() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        for mod in (
            "dbghelp.dll",
            "dbgcore.dll",
            "frida",
            "procexp64.exe",
            "scylla",
        ):
            if kernel32.GetModuleHandleW(mod):
                return True
    except Exception:
        pass
    return False

def _nt_debug_checks() -> bool:
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        process = kernel32.GetCurrentProcess()

        debug_port = ctypes.c_ulong()
        if (
            ntdll.NtQueryInformationProcess(process, 7, ctypes.byref(debug_port), ctypes.sizeof(debug_port), None) == 0
            and debug_port.value != 0
        ):
            return True

        debug_object = ctypes.c_void_p()
        if (
            ntdll.NtQueryInformationProcess(process, 30, ctypes.byref(debug_object), ctypes.sizeof(debug_object), None) == 0
            and debug_object.value
        ):
            return True

        debug_flags = ctypes.c_ulong()
        if (
            ntdll.NtQueryInformationProcess(process, 31, ctypes.byref(debug_flags), ctypes.sizeof(debug_flags), None) == 0
            and debug_flags.value == 0
        ):
            return True
    except Exception:
        pass
    return False

def _hide_from_debugger():
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        ThreadHideFromDebugger = 0x11
        ntdll.NtSetInformationThread(
            kernel32.GetCurrentThread(), ThreadHideFromDebugger, None, 0
        )
    except Exception:
        pass

def _anti_reverse_engineering_guard():
    if sys.gettrace() is not None:
        raise SystemExit()
    if os.environ.get("PYTHONINSPECT") or os.environ.get("PYTHONDEBUG"):
        raise SystemExit()
    if _detect_forbidden_processes():
        raise SystemExit()
    if _detect_suspicious_windows() or _detect_suspicious_modules():
        raise SystemExit()
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent():
            raise SystemExit()
        is_remote = ctypes.c_uint()
        kernel32.CheckRemoteDebuggerPresent(
            kernel32.GetCurrentProcess(), ctypes.byref(is_remote)
        )
        if is_remote.value:
            raise SystemExit()
        if _nt_debug_checks():
            raise SystemExit()
    except Exception:
        pass

def _guard_thread_loop():
    _hide_from_debugger()
    while True:
        try:
            _anti_reverse_engineering_guard()
        except SystemExit:
            os._exit(1)
        time.sleep(1)

_hide_from_debugger()
_anti_reverse_engineering_guard()
threading.Thread(target=_guard_thread_loop, daemon=True).start()

BOSSAC_URL = "https://downloads.arduino.cc/tools/bossac-1.9.1-arduino2-windows.tar.gz"
APP_NAME = "MouseControler - Fizo"
TOOLS_SUBDIR = "tools"

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEMOUSE = 0
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B

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
class RAWMOUSEBUTTONS(ctypes.Structure):
    _fields_ = [
        ('usButtonFlags', wintypes.USHORT),
        ('usButtonData', wintypes.USHORT),
    ]
class RAWMOUSEUNION(ctypes.Union):
    _fields_ = [
        ('ulButtons', wintypes.ULONG),
        ('buttons', RAWMOUSEBUTTONS),
    ]
class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ('u',)
    _fields_ = [
        ('usFlags', wintypes.USHORT),
        ('u', RAWMOUSEUNION),
        ('ulRawButtons', wintypes.ULONG),
        ('lLastX', wintypes.LONG),
        ('lLastY', wintypes.LONG),
        ('ulExtraInfo', wintypes.ULONG),
    ]
class RAWINPUTUNION(ctypes.Union):
    _fields_ = [('mouse', RAWMOUSE)]
class RAWINPUT(ctypes.Structure):
    _fields_ = [('header', RAWINPUTHEADER), ('data', RAWINPUTUNION)]
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ('usUsagePage', wintypes.USHORT),
        ('usUsage', wintypes.USHORT),
        ('dwFlags', wintypes.DWORD),
        ('hwndTarget', wintypes.HWND),
    ]
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]

GetRawInputData = user32.GetRawInputData
GetRawInputData.restype = UINT
GetRawInputData.argtypes = [HRAWINPUT, UINT, ctypes.c_void_p, ctypes.POINTER(UINT), UINT]
RegisterRawInputDevices = user32.RegisterRawInputDevices
RegisterRawInputDevices.restype = wintypes.BOOL
RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), UINT, UINT]

HHOOK = wintypes.HANDLE

if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_long):
    WPARAM = ctypes.c_ulong
    LPARAM = ctypes.c_long
    LRESULT = ctypes.c_long
else:
    WPARAM = ctypes.c_ulonglong
    LPARAM = ctypes.c_longlong
    LRESULT = ctypes.c_longlong

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
SetWindowsHookEx = user32.SetWindowsHookExW
SetWindowsHookEx.restype = HHOOK
SetWindowsHookEx.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
CallNextHookEx = user32.CallNextHookEx
CallNextHookEx.restype = LRESULT
CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
UnhookWindowsHookEx = user32.UnhookWindowsHookEx
UnhookWindowsHookEx.restype = wintypes.BOOL
UnhookWindowsHookEx.argtypes = [HHOOK]

class MouseBlocker:
    def __init__(self):
        self._hook = None
        self._proc = None

    def start(self):
        if self._hook:
            return

        def _callback(nCode, wParam, lParam):
            if nCode >= 0:
                return 1
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._proc = HOOKPROC(_callback)
        self._hook = SetWindowsHookEx(WH_MOUSE_LL, self._proc, 0, 0)
        if not self._hook:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err))

    def stop(self):
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None

class EscapeListener:
    def __init__(self, on_escape):
        self.on_escape = on_escape
        self._hook = None
        self._proc = None

    def start(self):
        if self._hook:
            return

        def _callback(nCode, wParam, lParam):
            if nCode >= 0 and wParam == WM_KEYDOWN:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_ESCAPE:
                    self.on_escape()
                    return 1
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._proc = HOOKPROC(_callback)
        self._hook = SetWindowsHookEx(WH_KEYBOARD_LL, self._proc, 0, 0)
        if not self._hook:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err))

    def stop(self):
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None

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
        try:
            addr = int(message)
        except TypeError:
            addr = message.__int__()

        pmsg = ctypes.cast(ctypes.c_void_p(addr), ctypes.POINTER(wintypes.MSG))
        msg = pmsg.contents

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
QProgressBar { border: 1px solid #2a2f3a; border-radius: 6px; background: #1c1f27; text-align: center; }
QProgressBar::chunk { background-color: #2e8bff; }
"""

def appdata_dir():
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder

def config_path():
    return os.path.join(appdata_dir(), "config.json")

def tools_dir():
    td = os.path.join(appdata_dir(), TOOLS_SUBDIR)
    os.makedirs(td, exist_ok=True)
    return td

def load_config():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg: dict):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass

def wait_for_bossa_port(timeout=5.0) -> str | None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        for p in serial.tools.list_ports.comports():
            if "bossa" in (p.description or "").lower():
                return p.device
        time.sleep(0.2)
    return None

def kick_bootloader_1200(port: str):
    try:
        s = serial.Serial(port=port, baudrate=1200, timeout=0.2)
        try:
            s.dtr = False; time.sleep(0.05); s.dtr = True; time.sleep(0.05)
        except Exception:
            pass
        s.close()
    except Exception:
        pass

def to_windows_bossac_port(port: str) -> str:
    try:
        n = int(port.replace("COM", ""))
        return port if n < 10 else r"\\.\%s" % port
    except Exception:
        return port

class MainWindow(QtWidgets.QMainWindow):
    flashProgress = QtCore.Signal(int)
    flashLogLine  = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mouse forwarder - Fizo")
        self.setMinimumSize(720, 440)
        self.statusBar()

        self.cfg = load_config()
        self._bossac_path = self.cfg.get("bossac_path") if self.cfg else None

        self.sender = SerialSender()
        self.sender.connectedChanged.connect(self.on_connected_changed)
        self.sender.statsUpdated.connect(self.on_stats)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        g1 = QtWidgets.QGroupBox("Arduino connection")
        l1 = QtWidgets.QGridLayout(g1)
        self.portCombo = QtWidgets.QComboBox()
        self.refreshBtn = QtWidgets.QPushButton("Refresh")
        self.connectBtn = QtWidgets.QPushButton("Connect")
        self.connectBtn.setCheckable(True)
        self.connectBtn.setEnabled(False)
        self.flashBtn = QtWidgets.QPushButton("Flash…")
        self.statusLbl = QtWidgets.QLabel("Disconnected")
        l1.addWidget(QtWidgets.QLabel("COM Port:"), 0, 0)
        l1.addWidget(self.portCombo, 0, 1)
        l1.addWidget(self.refreshBtn, 0, 2)
        l1.addWidget(self.connectBtn, 1, 1)
        l1.addWidget(self.flashBtn, 1, 2)
        l1.addWidget(self.statusLbl, 1, 3, alignment=QtCore.Qt.AlignRight)

        g2 = QtWidgets.QGroupBox("Mouse forwarding")
        l2 = QtWidgets.QGridLayout(g2)
        self.toggleBtn = QtWidgets.QPushButton("Start forwarding")
        self.toggleBtn.setCheckable(True)
        self.rateLbl = QtWidgets.QLabel("0 pkts/s")
        l2.addWidget(self.toggleBtn, 0, 0)
        l2.addWidget(self.rateLbl, 0, 1, alignment=QtCore.Qt.AlignRight)

        g3 = QtWidgets.QGroupBox("Status")
        l3 = QtWidgets.QVBoxLayout(g3)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        l3.addWidget(self.progress)
        l3.addWidget(self.log)

        tips = QtWidgets.QLabel(
            "Wiring:\n"
            "• Programming port → this PC (serial)\n"
            "• Native USB port → second PC (HID mouse)\n"
        )
        tips.setStyleSheet("color:#a9b1c7;")
        tips.setWordWrap(True)

        layout.addWidget(g1)
        layout.addWidget(g2)
        layout.addWidget(g3)
        layout.addWidget(tips)

        self.refreshBtn.clicked.connect(self.fill_ports)
        self.connectBtn.toggled.connect(self.on_connect_toggled)
        self.toggleBtn.toggled.connect(self.on_toggle_forwarding)
        self.flashBtn.clicked.connect(self.on_flash_clicked)

        self.forwarding = False
        self.filter = None
        self.blocker = MouseBlocker()
        self.escape = EscapeListener(self._on_escape)

        self.flashProgress.connect(self._on_flash_progress)
        self.flashLogLine.connect(self._on_flash_log)

        self.fill_ports()

    def fill_ports(self):
        current = self.portCombo.currentData()
        self.portCombo.clear()
        items = []
        for p in serial.tools.list_ports.comports():
            items.append((f"{p.device} — {p.description}", p.device, p.description or ""))
        items.sort(key=lambda x: ("arduino" not in x[0].lower() and "bossa" not in x[0].lower(), x[0].lower()))
        for label, dev, _desc in items:
            self.portCombo.addItem(label, dev)
            if dev == current:
                self.portCombo.setCurrentIndex(self.portCombo.count() - 1)
        if not items:
            self.portCombo.addItem("No ports found", None)
        self.connectBtn.setEnabled(bool(items))
        self.statusBar().showMessage(f"Found {len(items)} port(s)", 3000)

    def on_connect_toggled(self, checked):
        if checked:
            port = self.portCombo.currentData()
            ok = self.sender.open(port, 1000000) if port else False
            if not ok:
                self.statusLbl.setText("Failed")
                self.connectBtn.blockSignals(True); self.connectBtn.setChecked(False); self.connectBtn.blockSignals(False)
                self.connectBtn.setText("Connect")
                return
            self.statusLbl.setText("Connected @ 1,000,000")
            self.connectBtn.setText("Disconnect")
        else:
            self.sender.close()
            self.statusLbl.setText("Disconnected")
            self.connectBtn.setText("Connect")

    def on_connected_changed(self, ok:bool):
        self.connectBtn.blockSignals(True)
        self.connectBtn.setChecked(ok)
        self.connectBtn.blockSignals(False)
        if ok:
            self.statusLbl.setText("Connected")
        elif self.statusLbl.text() != "Failed":
            self.statusLbl.setText("Disconnected")

    def on_toggle_forwarding(self, enabled):
        self.forwarding = enabled
        self.toggleBtn.setText("Stop forwarding" if enabled else "Start forwarding")
        app = QtWidgets.QApplication.instance()
        if enabled:
            hwnd = int(self.winId())
            if not self.filter:
                self.filter = RawInputFilter(hwnd, self._on_delta)
                app.installNativeEventFilter(self.filter)
            self.blocker.start()
            self.escape.start()
        else:
            if self.filter:
                app.removeNativeEventFilter(self.filter)
                self.filter = None
            self.blocker.stop()
            self.escape.stop()

    def _on_escape(self):
        if self.forwarding:
            QtCore.QTimer.singleShot(0, lambda: self.toggleBtn.setChecked(False))

    def _on_delta(self, dx:int, dy:int):
        if self.forwarding and self.sender.ser:
            self.sender.send_delta(dx, dy)

    def on_stats(self, pps:int):
        self.rateLbl.setText(f"{pps} pkts/s")

    def closeEvent(self, event):
        try:
            self.blocker.stop()
            self.escape.stop()
        finally:
            super().closeEvent(event)

    def locate_bossac(self) -> str | None:
        if self._bossac_path and os.path.isfile(self._bossac_path):
            return self._bossac_path
        p = shutil.which("bossac") or shutil.which("bossac.exe")
        if p and os.path.isfile(p):
            self._bossac_path = p
            self.cfg["bossac_path"] = p
            save_config(self.cfg)
            return p
        resp = QtWidgets.QMessageBox.question(
            self, "Get bossac?", "bossac.exe not found.\n\nDownload the official portable build now ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if resp == QtWidgets.QMessageBox.Yes:
            p = self._auto_download_bossac()
            if p:
                self._bossac_path = p
                self.cfg["bossac_path"] = p
                save_config(self.cfg)
                return p
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Locate bossac.exe", "", "bossac (bossac.exe)")
        if path:
            self._bossac_path = path
            self.cfg["bossac_path"] = path
            save_config(self.cfg)
            return path
        return None

    def _auto_download_bossac(self) -> str | None:
        out_dir = os.path.join(tools_dir(), "bossac-1.9.1-arduino2")
        os.makedirs(out_dir, exist_ok=True)
        tar_path = os.path.join(out_dir, "bossac-1.9.1-arduino2-windows.tar.gz")
        exe_path = os.path.join(out_dir, "bossac.exe")

        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.appendPlainText(f"Downloading bossac from:\n{BOSSAC_URL}")

        done_evt = threading.Event()
        result = {"ok": False, "exe": None, "err": None}

        def worker():
            try:
                with urllib.request.urlopen(BOSSAC_URL) as r:
                    total = int(r.headers.get("Content-Length", "0")) or 0
                    got = 0
                    with open(tar_path, "wb") as f:
                        while True:
                            chunk = r.read(1024 * 64)
                            if not chunk: break
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                pct = max(0, min(100, int(got * 100 / total)))
                                QtCore.QMetaObject.invokeMethod(self, "flashProgress", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, pct))
                QtCore.QMetaObject.invokeMethod(self, "flashLogLine", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, "Download complete. Extracting…"))

                found = None
                with tarfile.open(tar_path, "r:gz") as tf:
                    for m in tf.getmembers():
                        name = m.name.replace("\\", "/").lower()
                        if name.endswith("/bossac.exe") or name.endswith("bossac.exe"):
                            tf.extract(m, out_dir)
                            extracted = os.path.join(out_dir, m.name)
                            base = os.path.join(out_dir, "bossac.exe")
                            try:
                                if os.path.abspath(extracted) != os.path.abspath(base):
                                    shutil.move(extracted, base)
                            except Exception:
                                pass
                            found = base
                            break
                if not found or not os.path.isfile(exe_path):
                    raise RuntimeError("bossac.exe not found in archive")

                result["ok"] = True
                result["exe"] = exe_path
            except Exception as e:
                result["ok"] = False
                result["err"] = str(e)
            finally:
                done_evt.set()

        threading.Thread(target=worker, daemon=True).start()
        while not done_evt.is_set():
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)

        if result["ok"]:
            self.flashProgress.emit(100)
            self.log.appendPlainText(f"bossac ready: {result['exe']}")
            return result["exe"]
        else:
            self.log.appendPlainText(f"Auto-download failed: {result['err']}")
            return None

    def on_flash_clicked(self):
        bin_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select compiled .bin", "", "Binary (*.bin)")
        if not bin_path:
            return

        bossac = self.locate_bossac()
        if not bossac:
            QtWidgets.QMessageBox.warning(self, "bossac not found", "bossac.exe is required for flashing.")
            return

        self.progress.setValue(0)
        self.log.clear()
        self.statusBar().showMessage("Preparing bootloader…")

        selected_port = self.portCombo.currentData()
        if selected_port:
            kick_bootloader_1200(selected_port)

        bossa_port = wait_for_bossa_port(timeout=5.0) or selected_port
        if not bossa_port:
            QtWidgets.QMessageBox.warning(self, "No port", "No serial port selected and Bossa Program Port not found.")
            return

        bossaport_arg = to_windows_bossac_port(bossa_port)
        args = [
            bossac,
            "-i", "-d",
            f"--port={bossaport_arg}",
            "-U", "true",
            "-e", "-w", "-v",
            bin_path,
            "-R"
        ]

        self.setEnabled(False)
        self.statusBar().showMessage(f"Flashing on {bossa_port}…")

        def run_bossac():
            ok = False
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    QtCore.QMetaObject.invokeMethod(self, "flashLogLine", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, line))
                    m = re.search(r'(\d{1,3})\s*%', line)
                    if m:
                        pct = max(0, min(100, int(m.group(1))))
                        QtCore.QMetaObject.invokeMethod(self, "flashProgress", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, pct))
                    else:
                        m2 = re.search(r'\((\d+)\s*/\s*(\d+)\s*pages?\)', line, re.IGNORECASE)
                        if m2:
                            cur, total = int(m2.group(1)), max(1, int(m2.group(2)))
                            pct = int((cur / total) * 100)
                            QtCore.QMetaObject.invokeMethod(self, "flashProgress", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, pct))
                proc.wait()
                ok = (proc.returncode == 0)
            except Exception as e:
                QtCore.QMetaObject.invokeMethod(self, "flashLogLine", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"Error: {e}"))
                ok = False
            finally:
                if ok:
                    QtCore.QMetaObject.invokeMethod(self, "flashProgress", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, 100))
                QtCore.QMetaObject.invokeMethod(self, "_flash_done",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(bool, ok),
                    QtCore.Q_ARG(str, bossa_port))

        threading.Thread(target=run_bossac, daemon=True).start()

    @QtCore.Slot(int)
    def _on_flash_progress(self, pct:int):
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)

    @QtCore.Slot(str)
    def _on_flash_log(self, line:str):
        self.log.appendPlainText(line)

    @QtCore.Slot(bool, str)
    def _flash_done(self, ok:bool, port_used:str):
        self.setEnabled(True)
        self.fill_ports()
        if ok:
            self.statusBar().showMessage(f"Flash OK on {port_used}", 5000)
            QtWidgets.QMessageBox.information(self, "Flash complete", "Upload finished successfully.")
        else:
            self.statusBar().showMessage("Flash failed", 5000)
            QtWidgets.QMessageBox.critical(self, "Flash FAILED", "bossac returned an error. See the log for details.")

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
