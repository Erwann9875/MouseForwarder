import sys, time
from typing import Optional
from PySide6 import QtCore, QtGui


class NDIReceiver(QtCore.QObject):
    connectedChanged = QtCore.Signal(bool)
    sourcesUpdated = QtCore.Signal(object)
    frameReady = QtCore.Signal(QtGui.QImage)

    def __init__(self):
        super().__init__()
        self._running = False
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[QtCore.QObject] = None
        self._ndi_available = False
        self._source_name: Optional[str] = None

        try:
            import NDIlib as _ndi  # noqa: F401
            self._ndi_available = True
        except Exception:
            self._ndi_available = False

    @QtCore.Slot()
    def refresh_sources(self):
        if not self._ndi_available:
            self.sourcesUpdated.emit(["Dummy Pattern"])
            return
        try:
            import NDIlib as ndi
            if not ndi.initialize():
                self.sourcesUpdated.emit([])
                return
            find = ndi.find_create()
            try:
                sources = ndi.find_get_current_sources(find) or []
                names = [s.ndi_name for s in sources]
            finally:
                ndi.find_destroy(find)
                ndi.destroy()
            self.sourcesUpdated.emit(names)
        except Exception:
            self.sourcesUpdated.emit([])

    def start(self, source_name: Optional[str] = None):
        if self._running:
            return
        self._running = True
        self._source_name = source_name
        if self._ndi_available and source_name:
            self._start_ndi_worker(source_name)
        else:
            self._start_dummy_worker()
        self.connectedChanged.emit(True)

    def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            if self._worker is not None and hasattr(self._worker, 'running'):
                setattr(self._worker, 'running', False)
        except Exception:
            pass
        if self._thread:
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None
        self.connectedChanged.emit(False)

    def _start_dummy_worker(self):
        class DummyWorker(QtCore.QObject):
            frame = QtCore.Signal(QtGui.QImage)
            runningChanged = QtCore.Signal(bool)
            def __init__(self, parent=None):
                super().__init__(parent)
                self.running = True
            @QtCore.Slot()
            def loop(self):
                w, h = 640, 360
                hue = 0
                last = time.time()
                while self.running:
                    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
                    painter = QtGui.QPainter(img)
                    c1 = QtGui.QColor.fromHsv(hue % 360, 180, 255)
                    c2 = QtGui.QColor.fromHsv((hue + 120) % 360, 180, 255)
                    grad = QtGui.QLinearGradient(0, 0, w, h)
                    grad.setColorAt(0.0, c1)
                    grad.setColorAt(1.0, c2)
                    painter.fillRect(0, 0, w, h, QtGui.QBrush(grad))
                    painter.setPen(QtGui.QColor("white"))
                    painter.setFont(QtGui.QFont("Segoe UI", 18))
                    ts = time.strftime("%H:%M:%S")
                    painter.drawText(12, 28, f"Dummy NDI feed — {ts}")
                    painter.end()
                    self.frame.emit(img)
                    hue = (hue + 2) % 360
                    now = time.time()
                    dt = now - last
                    sleep = max(0.0, (1/30) - dt)
                    end_time = now + sleep
                    while self.running and time.time() < end_time:
                        time.sleep(0.005)
                    last = now

        worker = DummyWorker()
        th = QtCore.QThread(self)
        worker.moveToThread(th)
        th.started.connect(worker.loop)
        worker.frame.connect(self.frameReady)
        self._worker = worker
        th.start()
        self._thread = th

    def _start_ndi_worker(self, source_name: str):
        import NDIlib as ndi  # type: ignore

        class NDIWorker(QtCore.QObject):
            frame = QtCore.Signal(QtGui.QImage)
            def __init__(self, src_name: str):
                super().__init__()
                self.src_name = src_name
                self.running = True
            @QtCore.Slot()
            def loop(self):
                if not ndi.initialize():
                    return
                find = ndi.find_create()
                recv = None
                try:
                    sources = ndi.find_get_current_sources(find) or []
                    target = None
                    for s in sources:
                        if s.ndi_name == self.src_name:
                            target = s
                            break
                    if target is None:
                        return
                    settings = ndi.RecvCreate_v3()
                    settings.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
                    recv = ndi.recv_create_v3(settings)
                    ndi.recv_connect(recv, target)
                    while self.running:
                        t, v, a, m = ndi.recv_capture_v3(recv, 200)
                        if t == ndi.FRAME_TYPE_VIDEO:
                            w, h = v.xres, v.yres
                            buf = QtCore.QByteArray(int(v.data_size), 0)
                            QtCore.qMemCopy(buf.data(), v.data, v.data_size)
                            img = QtGui.QImage(
                                buf, w, h, v.line_stride_in_bytes, QtGui.QImage.Format.Format_BGR30
                            )
                            img = img.copy()
                            self.frame.emit(img)
                            ndi.recv_free_video_v2(recv, v)
                        if not self.running:
                            break
                finally:
                    if recv:
                        ndi.recv_destroy(recv)
                    ndi.find_destroy(find)
                    ndi.destroy()

        worker = NDIWorker(source_name)
        th = QtCore.QThread(self)
        worker.moveToThread(th)
        th.started.connect(worker.loop)
        worker.frame.connect(self.frameReady)
        self._worker = worker
        th.start()
        self._thread = th
