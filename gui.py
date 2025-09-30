import sys, threading, time, subprocess, os, shutil, json, re, tarfile, zipfile, urllib.request, tempfile, base64
import serial, serial.tools.list_ports
from PySide6 import QtCore, QtWidgets, QtGui

if sys.platform != "win32":
    raise SystemExit("This app supports Windows only.")

from security import start_security_guard
from auth_guard import start_integrity_monitor, set_session_token, require_auth
from mouse_blocker import MouseBlocker, EscapeListener, RawInputFilter
from serial_sender import SerialSender
from whip_server import WhipServer
from constants import (
    DEFAULT_BLOCKED,
    BOSSAC_URL,
    ARDUINO_CLI_URL,
    BOARDS,
    APP_NAME,
    TOOLS_SUBDIR,
)

start_security_guard()
start_integrity_monitor()

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


def authenticate_user(username: str, password: str) -> tuple[bool, str | None]:
    # import requests
    # try:
    #     r = requests.post(
    #         "https://api.test.com/login",
    #         json={"username": username, "password": password},
    #         timeout=5,
    #     )
    #     r.raise_for_status()
    #     data = r.json()
    #     return True, data.get("token")
    # except Exception:
    #     return False, None

    if username == "test" and password == "test":
        return True, base64.b64encode(os.urandom(16)).decode('ascii')
    return False, None


class LoginDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sign in")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.userEdit = QtWidgets.QLineEdit()
        self.passEdit = QtWidgets.QLineEdit()
        self.passEdit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.userEdit.setPlaceholderText("Username")
        self.passEdit.setPlaceholderText("Password")
        form.addRow("Username", self.userEdit)
        form.addRow("Password", self.passEdit)

        self.errorLbl = QtWidgets.QLabel("")
        self.errorLbl.setStyleSheet("color:#ff6b6b;")

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._try_login)
        btns.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(self.errorLbl)
        layout.addWidget(btns)

        self.userEdit.returnPressed.connect(self._try_login)
        self.passEdit.returnPressed.connect(self._try_login)

        self.userEdit.setText("")
        self.passEdit.setText("")

        self.token: str | None = None

    def _try_login(self):
        u = self.userEdit.text().strip()
        p = self.passEdit.text()
        ok, token = authenticate_user(u, p)
        if ok:
            try:
                set_session_token(u, p)
            except Exception:
                pass
            self.token = token
            self.accept()
        else:
            self.errorLbl.setText("Invalid credentials. Use test/test for now.")

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
        self._board_name = self.cfg.get("board", "Arduino Due")

        self.sender = SerialSender()
        self.sender.connectedChanged.connect(self.on_connected_changed)
        self.sender.statsUpdated.connect(self.on_stats)

        self.whip = WhipServer()
        self.whip.startedChanged.connect(self._on_whip_started)
        self.whip.urlsUpdated.connect(self._on_whip_urls)
        self.whip.statusChanged.connect(self._on_whip_status)
        self.whip.frameReady.connect(self._on_whip_frame)
        self._whip_last_frame: QtGui.QImage | None = None
        self._whip_debug_win = None

        tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(tabs)
        mousePage = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(mousePage)

        g1 = QtWidgets.QGroupBox("Arduino connection")
        l1 = QtWidgets.QGridLayout(g1)
        self.boardCombo = QtWidgets.QComboBox()
        for name, data in BOARDS.items():
            self.boardCombo.addItem(name, data)
        idx = self.boardCombo.findText(self._board_name)
        if idx != -1:
            self.boardCombo.setCurrentIndex(idx)
        self.boardCombo.currentTextChanged.connect(self._on_board_changed)
        self.portCombo = QtWidgets.QComboBox()
        self.refreshBtn = QtWidgets.QPushButton("Refresh")
        self.connectBtn = QtWidgets.QPushButton("Connect")
        self.connectBtn.setCheckable(True)
        self.connectBtn.setEnabled(False)
        self.flashBtn = QtWidgets.QPushButton("Flash…")
        self.clearBtn = QtWidgets.QPushButton("Clear packages")
        self.statusLbl = QtWidgets.QLabel("Disconnected")

        l1.addWidget(QtWidgets.QLabel("Board:"), 0, 0)
        l1.addWidget(self.boardCombo, 0, 1, 1, 2)
        l1.addWidget(QtWidgets.QLabel("COM Port:"), 1, 0)
        l1.addWidget(self.portCombo, 1, 1)
        l1.addWidget(self.refreshBtn, 1, 2)
        l1.addWidget(self.connectBtn, 2, 1)
        l1.addWidget(self.flashBtn, 2, 2)
        l1.addWidget(self.statusLbl, 2, 3, alignment=QtCore.Qt.AlignRight)
        l1.addWidget(self.clearBtn, 3, 1, 1, 2)

        g2 = QtWidgets.QGroupBox("Mouse forwarding")
        l2 = QtWidgets.QGridLayout(g2)
        self.toggleBtn = QtWidgets.QPushButton("Start forwarding")
        self.toggleBtn.setCheckable(True)
        self.rateLbl = QtWidgets.QLabel("0 pkts/s")
        l2.addWidget(self.toggleBtn, 0, 0)
        l2.addWidget(self.rateLbl, 0, 1, alignment=QtCore.Qt.AlignRight)

        btnLayout = QtWidgets.QHBoxLayout()
        self.blockLeft = QtWidgets.QCheckBox("Left")
        self.blockRight = QtWidgets.QCheckBox("Right")
        self.blockMiddle = QtWidgets.QCheckBox("Middle")
        self.blockBack = QtWidgets.QCheckBox("Back")
        self.blockForward = QtWidgets.QCheckBox("Forward")
        self.blockWheel = QtWidgets.QCheckBox("Wheel")
        for cb in (
            self.blockLeft,
            self.blockRight,
            self.blockMiddle,
            self.blockBack,
            self.blockForward,
            self.blockWheel,
        ):
            btnLayout.addWidget(cb)
        l2.addLayout(btnLayout, 1, 0, 1, 2)

        blocked = self.cfg.get("blocked_buttons", DEFAULT_BLOCKED)
        self.blockLeft.setChecked("left" in blocked)
        self.blockRight.setChecked("right" in blocked)
        self.blockMiddle.setChecked("middle" in blocked)
        self.blockBack.setChecked("back" in blocked)
        self.blockForward.setChecked("forward" in blocked)
        self.blockWheel.setChecked("wheel" in blocked)

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
        tabs.addTab(mousePage, "Mouse")

        whipPage = QtWidgets.QWidget()
        gl = QtWidgets.QGridLayout(whipPage)
        self.whipPort = QtWidgets.QSpinBox()
        self.whipPort.setRange(1, 65535)
        self.whipPort.setValue(8080)
        self.whipStart = QtWidgets.QPushButton("Start server")
        self.whipStart.setCheckable(True)
        self.whipPreview = QtWidgets.QLabel()
        self.whipPreview.setMinimumSize(320, 180)
        self.whipPreview.setAlignment(QtCore.Qt.AlignCenter)
        self.whipPreview.setStyleSheet("background:#0b0d12;border:1px solid #2a2f3a;")
        self.whipStats = QtWidgets.QLabel("")
        self.whipStats.setStyleSheet("color:#a9b1c7;")
        self.whipOpenDebug = QtWidgets.QPushButton("Open debug")
        self.whipUrls = QtWidgets.QPlainTextEdit()
        self.whipUrls.setReadOnly(True)
        self.whipUrls.setMaximumBlockCount(100)
        self.whipCopy = QtWidgets.QPushButton("Copy URLs")
        gl.addWidget(QtWidgets.QLabel("Port:"), 0, 0)
        gl.addWidget(self.whipPort, 0, 1)
        gl.addWidget(self.whipStart, 0, 2)
        gl.addWidget(QtWidgets.QLabel("WHIP ingest URLs:"), 1, 0)
        gl.addWidget(self.whipUrls, 2, 0, 1, 3)
        gl.addWidget(self.whipCopy, 3, 1)
        gl.addWidget(self.whipOpenDebug, 3, 2)
        gl.addWidget(self.whipPreview, 4, 0, 1, 3)
        gl.addWidget(self.whipStats, 5, 0, 1, 3)
        cropBox = QtWidgets.QGroupBox("Crop")
        cropLayout = QtWidgets.QGridLayout(cropBox)
        self.cropEnable = QtWidgets.QCheckBox("Enable crop")
        self.cropEnable.setChecked(False)
        self.cropCenter = QtWidgets.QCheckBox("Center")
        self.cropCenter.setChecked(True)
        self.cropW = QtWidgets.QSpinBox()
        self.cropW.setRange(1, 8192)
        self.cropW.setValue(320)
        self.cropH = QtWidgets.QSpinBox()
        self.cropH.setRange(1, 8192)
        self.cropH.setValue(320)
        self.cropX = QtWidgets.QSpinBox()
        self.cropX.setRange(0, 32768)
        self.cropX.setValue(0)
        self.cropY = QtWidgets.QSpinBox()
        self.cropY.setRange(0, 32768)
        self.cropY.setValue(0)
        cropLayout.addWidget(self.cropEnable, 0, 0)
        cropLayout.addWidget(self.cropCenter, 0, 1)
        cropLayout.addWidget(QtWidgets.QLabel("W:"), 1, 0)
        cropLayout.addWidget(self.cropW, 1, 1)
        cropLayout.addWidget(QtWidgets.QLabel("H:"), 1, 2)
        cropLayout.addWidget(self.cropH, 1, 3)
        cropLayout.addWidget(QtWidgets.QLabel("X:"), 2, 0)
        cropLayout.addWidget(self.cropX, 2, 1)
        cropLayout.addWidget(QtWidgets.QLabel("Y:"), 2, 2)
        cropLayout.addWidget(self.cropY, 2, 3)
        gl.addWidget(cropBox, 6, 0, 1, 3)
        tabs.addTab(whipPage, "WHIP")

        self.whipStart.toggled.connect(self._on_whip_start_toggled)
        self.whipCopy.clicked.connect(self._copy_whip_urls)
        self.whipOpenDebug.clicked.connect(self._open_whip_debug)

        self.blocker = MouseBlocker()
        self.blocker.set_blocked(self._blocked_buttons())
        self.escape = EscapeListener(self._on_escape)

        self.refreshBtn.clicked.connect(self.fill_ports)
        self.connectBtn.toggled.connect(self.on_connect_toggled)
        self.toggleBtn.toggled.connect(self.on_toggle_forwarding)
        self.flashBtn.clicked.connect(self.on_flash_clicked)
        self.clearBtn.clicked.connect(self._on_clear_packages)

        for cb in (
            self.blockLeft,
            self.blockRight,
            self.blockMiddle,
            self.blockBack,
            self.blockForward,
            self.blockWheel,
        ):
            cb.stateChanged.connect(self._on_block_boxes_changed)

        self.forwarding = False
        self.filter = None

        self.flashProgress.connect(self._on_flash_progress)
        self.flashLogLine.connect(self._on_flash_log)

        self.fill_ports()

        self._whip_last_frame_t: float | None = None
        self._whip_fps_ema: float = 0.0
        self._whip_ms_ema: float = 0.0

        def _on_crop_changed_local():
            center = self.cropCenter.isChecked()
            self.cropX.setEnabled(not center)
            self.cropY.setEnabled(not center)
            try:
                self.whip.set_crop_config(
                    self.cropEnable.isChecked(),
                    int(self.cropX.value()),
                    int(self.cropY.value()),
                    int(self.cropW.value()),
                    int(self.cropH.value()),
                    center,
                )
            except Exception:
                pass

        self.cropEnable.toggled.connect(_on_crop_changed_local)
        self.cropCenter.toggled.connect(_on_crop_changed_local)
        self.cropW.valueChanged.connect(lambda _v: _on_crop_changed_local())
        self.cropH.valueChanged.connect(lambda _v: _on_crop_changed_local())
        self.cropX.valueChanged.connect(lambda _v: _on_crop_changed_local())
        self.cropY.valueChanged.connect(lambda _v: _on_crop_changed_local())
        _on_crop_changed_local()

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
        try:
            require_auth()
        except Exception:
            enabled = False
        self.forwarding = enabled
        self.toggleBtn.setText("Stop forwarding" if enabled else "Start forwarding")
        app = QtWidgets.QApplication.instance()
        if enabled:
            hwnd = int(self.winId())
            if not self.filter:
                self.filter = RawInputFilter(hwnd, self._on_delta)
                app.installNativeEventFilter(self.filter)
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

    def _blocked_buttons(self) -> set[str]:
        buttons = set()
        if self.blockLeft.isChecked():
            buttons.add("left")
        if self.blockRight.isChecked():
            buttons.add("right")
        if self.blockMiddle.isChecked():
            buttons.add("middle")
        if self.blockBack.isChecked():
            buttons.add("back")
        if self.blockForward.isChecked():
            buttons.add("forward")
        if self.blockWheel.isChecked():
            buttons.add("wheel")
        return buttons

    def _on_block_boxes_changed(self):
        self.blocker.set_blocked(self._blocked_buttons())
        self.cfg["blocked_buttons"] = list(self._blocked_buttons())
        save_config(self.cfg)

    def _on_board_changed(self, name: str):
        self._board_name = name
        self.cfg["board"] = name
        save_config(self.cfg)

    def on_stats(self, pps:int):
        self.rateLbl.setText(f"{pps} pkts/s")

    def closeEvent(self, event):
        try:
            self.blocker.stop()
            self.escape.stop()
            try:
                self.whip.stop()
            except Exception:
                pass
        finally:
            super().closeEvent(event)

    def _run_cli(self, args: list[str]) -> bool:
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            while True:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    QtWidgets.QApplication.processEvents()
                    time.sleep(0.01)
                    continue
                self.log.appendPlainText(line.rstrip("\r\n"))
                QtWidgets.QApplication.processEvents()
            return proc.returncode == 0
        except Exception as e:
            self.log.appendPlainText(f"Error: {e}")
            return False

    def locate_arduino_cli(self) -> str | None:
        exe_path = os.path.join(tools_dir(), "arduino-cli.exe")
        if os.path.isfile(exe_path):
            return exe_path
        resp = QtWidgets.QMessageBox.question(
            self,
            "Get arduino-cli?",
            "arduino-cli.exe not found.\n\nDownload the official build now?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if resp != QtWidgets.QMessageBox.Yes:
            return None

        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.appendPlainText(f"Downloading arduino-cli from:\n{ARDUINO_CLI_URL}")

        zip_path = os.path.join(tools_dir(), "arduino-cli.zip")
        done_evt = threading.Event()
        result = {"ok": False, "err": None}

        def worker():
            try:
                with urllib.request.urlopen(ARDUINO_CLI_URL) as r:
                    total = int(r.headers.get("Content-Length", "0")) or 0
                    got = 0
                    with open(zip_path, "wb") as f:
                        while True:
                            chunk = r.read(1024 * 64)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                pct = max(0, min(100, int(got * 100 / total)))
                                QtCore.QMetaObject.invokeMethod(
                                    self, "flashProgress", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, pct)
                                )
                QtCore.QMetaObject.invokeMethod(
                    self, "flashLogLine", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, "Download complete. Extracting…")
                )
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extract("arduino-cli.exe", tools_dir())
                result["ok"] = True
            except Exception as e:
                result["err"] = str(e)
            finally:
                done_evt.set()

        threading.Thread(target=worker, daemon=True).start()
        while not done_evt.is_set():
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)

        if result["ok"] and os.path.isfile(exe_path):
            self.flashProgress.emit(100)
            self.log.appendPlainText(f"arduino-cli ready: {exe_path}")
            return exe_path
        else:
            self.log.appendPlainText(f"Auto-download failed: {result['err']}")
            return None

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

    def _ensure_core_installed(self, cli:str, fqbn:str)->bool:
        core = ":".join(fqbn.split(":")[:2])
        try:
            out = subprocess.check_output([cli, "core", "list"], text=True, stderr=subprocess.STDOUT)
            if core in out:
                return True
        except Exception:
            pass
        try:
            self.log.appendPlainText(f"Installing core {core}…")
            if not self._run_cli([cli, "core", "update-index"]):
                raise RuntimeError("core update-index failed")
            if not self._run_cli([cli, "lib", "install", "Mouse"]):
                raise RuntimeError("lib install Mouse failed")
            if not self._run_cli([cli, "core", "install", core]):
                raise RuntimeError("core install failed")
            return True
        except Exception as e:
            self.log.appendPlainText(f"Core install failed: {e}")
            QtWidgets.QMessageBox.critical(self, "Core install failed", f"Could not install {core}. See log.")
            return False

    def _on_clear_packages(self):
        cli = self.locate_arduino_cli()
        if not cli:
            return
        board = self.boardCombo.currentData()
        core = ":".join(board["fqbn"].split(":")[:2])
        self.log.appendPlainText("Removing library…")
        self._run_cli([cli, "lib", "uninstall", "Mouse"])
        self._run_cli([cli, "core", "uninstall", core])

    def build_firmware(self) -> str | None:
        cli = self.locate_arduino_cli()
        if not cli:
            return None
        board = self.boardCombo.currentData()
        if not self._ensure_core_installed(cli, board["fqbn"]):
            return None
        build_dir = tempfile.mkdtemp()
        sketch = os.path.join(os.path.dirname(__file__), "ControlMouse.ino")
        board = self.boardCombo.currentData()
        args = [
            cli,
            "compile",
            "--fqbn",
            board["fqbn"],
            "--build-path",
            build_dir,
            sketch,
        ]
        self.log.appendPlainText("Compiling sketch…")
        ok = False
        try:
            ok = self._run_cli(args)
        except Exception as e:
            self.log.appendPlainText(str(e))
        if not ok:
            QtWidgets.QMessageBox.critical(self, "Build failed", "arduino-cli compile failed. See log.")
            return None
        return os.path.join(build_dir, f"ControlMouse.ino{board['ext']}")

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
        bin_path = self.build_firmware()
        if not bin_path:
            return

        board = self.boardCombo.currentData()
        if board["flash"] == "bossac":
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
                QtWidgets.QMessageBox.warning(self, "No port", "No serial port selected and bossa program port not found.")
                return

            bossaport_arg = to_windows_bossac_port(bossa_port)
            args = [
                bossac,
                "-i", "-d",
                "-p", bossaport_arg,
                "--unlock=false",
                "-e", "-w", "-v",
                "-b",
                bin_path,
                "-R",
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
        else:
            cli = self.locate_arduino_cli()
            if not cli:
                QtWidgets.QMessageBox.warning(self, "arduino-cli not found", "arduino-cli.exe is required for flashing.")
                return
            selected_port = self.portCombo.currentData()
            if not selected_port:
                QtWidgets.QMessageBox.warning(self, "No port", "No serial port selected.")
                return
            self.progress.setValue(0)
            self.log.clear()
            self.setEnabled(False)
            self.statusBar().showMessage(f"Flashing on {selected_port}…")
            args = [
                cli,
                "upload",
                "--fqbn", board["fqbn"],
                "--port", selected_port,
                "--input-file", bin_path,
            ]

            def run_upload():
                ok = False
                try:
                    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                    for line in proc.stdout:
                        line = line.rstrip("\r\n")
                        QtCore.QMetaObject.invokeMethod(self, "flashLogLine", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, line))
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
                        QtCore.Q_ARG(str, selected_port))

            threading.Thread(target=run_upload, daemon=True).start()

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
            QtWidgets.QMessageBox.critical(self, "Flash FAILED", "Upload returned an error. See the log for details.")

    @QtCore.Slot(bool)
    def _on_whip_started(self, ok: bool):
        self.whipStart.blockSignals(True)
        self.whipStart.setChecked(ok)
        self.whipStart.blockSignals(False)
        self.whipStart.setText("Stop Server" if ok else "Start Server")
        self.statusBar().showMessage("WHIP server running" if ok else "WHIP server stopped", 3000)
        if not ok:
            self._whip_last_frame = None
            self.whipPreview.clear()
            self.whipStats.setText("")
            self._whip_last_frame_t = None
            self._whip_fps_ema = 0.0
            self._whip_ms_ema = 0.0
            if hasattr(self, '_whip_debug_win') and self._whip_debug_win is not None:
                try:
                    self._whip_debug_win.update_frame(None)
                except Exception:
                    pass

    def _on_whip_status(self, text: str):
        if text:
            self.statusBar().showMessage(text, 4000)

    def _on_whip_urls(self, urls: list[str]):
        try:
            self.whipUrls.setPlainText("\n".join(urls))
        except Exception:
            pass

    @QtCore.Slot()
    def _open_whip_debug(self):
        if not hasattr(self, '_whip_debug_win') or self._whip_debug_win is None:
            self._whip_debug_win = WHIPDebugWindow(self)
            if self._whip_last_frame is not None:
                self._whip_debug_win.update_frame(self._whip_last_frame)
        self._whip_debug_win.show()
        self._whip_debug_win.raise_()
        self._whip_debug_win.activateWindow()

    @QtCore.Slot(QtGui.QImage)
    def _on_whip_frame(self, img: QtGui.QImage):
        self._whip_last_frame = img
        if not img.isNull():
            pm = QtGui.QPixmap.fromImage(img)
            self.whipPreview.setPixmap(pm.scaled(self.whipPreview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        t = time.time()
        if self._whip_last_frame_t is not None:
            dt = max(1e-6, t - self._whip_last_frame_t)
            cur_fps = 1.0 / dt
            cur_ms = dt * 1000.0
            self._whip_fps_ema = (self._whip_fps_ema * 0.9) + (cur_fps * 0.1) if self._whip_fps_ema > 0 else cur_fps
            self._whip_ms_ema = (self._whip_ms_ema * 0.9) + (cur_ms * 0.1) if self._whip_ms_ema > 0 else cur_ms
            try:
                self.whipStats.setText(f"{img.width()}x{img.height()}  |  ~{self._whip_fps_ema:.1f} fps  |  ~{self._whip_ms_ema:.1f} ms")
            except Exception:
                pass
        self._whip_last_frame_t = t
        if hasattr(self, '_whip_debug_win') and self._whip_debug_win is not None:
            self._whip_debug_win.update_frame(img)

    def _on_whip_start_toggled(self, checked: bool):
        if checked:
            self.whip.start(self.whipPort.value())
        else:
            self.whip.stop()
            self._on_whip_started(False)

    def _copy_whip_urls(self):
        txt = self.whipUrls.toPlainText()
        if txt:
            QtWidgets.QApplication.clipboard().setText(txt)
            self.statusBar().showMessage("Copied WHIP URLs to clipboard", 3000)

class WHIPDebugWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WHIP Debug")
        self.setMinimumSize(560, 315)
        v = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QLabel()
        self.view.setAlignment(QtCore.Qt.AlignCenter)
        self.view.setStyleSheet("background:#0b0d12;border:1px solid #2a2f3a;")
        self.stats = QtWidgets.QLabel("")
        v.addWidget(self.view)
        v.addWidget(self.stats)
        self._last_time = None
        self._fps = 0.0
        self._ms = 0.0

    def update_frame(self, img: QtGui.QImage | None):
        if img is None or (hasattr(img, 'isNull') and img.isNull()):
            self.view.clear()
            self.stats.setText("")
            self._last_time = None
            self._fps = 0.0
            self._ms = 0.0
            return
        pm = QtGui.QPixmap.fromImage(img)
        self.view.setPixmap(pm.scaled(self.view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        t = time.time()
        if self._last_time is not None:
            dt = max(1e-3, t - self._last_time)
            self._fps = self._fps * 0.9 + (1.0/dt) * 0.1
            self._ms = self._ms * 0.9 + (dt * 1000.0) * 0.1 if self._ms > 0 else (dt * 1000.0)
        self._last_time = t
        self.stats.setText(f"{img.width()}x{img.height()}  |  ~{self._fps:.1f} fps  |  ~{self._ms:.1f} ms")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    login = LoginDialog()
    if login.exec() != QtWidgets.QDialog.Accepted:
        sys.exit(0)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
