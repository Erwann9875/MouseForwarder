import asyncio
import socket
import time
from typing import List, Optional

from PySide6 import QtCore, QtGui

class WhipServer(QtCore.QObject):
    startedChanged = QtCore.Signal(bool)
    urlsUpdated = QtCore.Signal(object)
    statusChanged = QtCore.Signal(str)
    frameReady = QtCore.Signal(QtGui.QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[QtCore.QObject] = None
        self._running = False
        self._port = 8080

    @QtCore.Slot(int)
    def start(self, port: int = 8080):
        if self._running:
            return
        self._running = True
        self._port = int(port or 8080)
        self._start_worker()
        self.startedChanged.emit(True)

    @QtCore.Slot()
    def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            if self._worker is not None and hasattr(self._worker, 'stop_async'):
                self._worker.stop_async()
        except Exception:
            pass
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.startedChanged.emit(False)

    def _start_worker(self):
        parent = self

        class ServerWorker(QtCore.QObject):
            def __init__(self, port: int):
                super().__init__()
                self._port = port
                self._loop: Optional[asyncio.AbstractEventLoop] = None
                self._task: Optional[asyncio.Task] = None
                self._stop_event: Optional[asyncio.Event] = None
                self._runner = None
                self._site = None
                self._pcs = set()
                self._aiohttp_ok = False
                self._aiortc_ok = False
                try:
                    import aiohttp  # noqa: F401
                    from aiohttp import web  # noqa: F401
                    self._aiohttp_ok = True
                except Exception:
                    self._aiohttp_ok = False
                try:
                    from aiortc import RTCPeerConnection  # noqa: F401
                    self._aiortc_ok = True
                except Exception:
                    self._aiortc_ok = False

            def stop_async(self):
                if self._loop and self._stop_event:
                    def _set():
                        if not self._stop_event.is_set():
                            self._stop_event.set()
                    self._loop.call_soon_threadsafe(_set)

            def _local_urls(self) -> List[str]:
                addrs: List[str] = ["127.0.0.1"]
                try:
                    hn = socket.gethostname()
                    _, _, ips = socket.gethostbyname_ex(hn)
                    for ip in ips:
                        if ip.startswith("127."):
                            continue
                        if ":" in ip:
                            continue
                        addrs.append(ip)
                except Exception:
                    pass
                urls = [f"http://{ip}:{self._port}/whip" for ip in sorted(set(addrs))]
                return urls

            @QtCore.Slot()
            def loop(self):
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._stop_event = asyncio.Event()
                self._task = self._loop.create_task(self._main())
                try:
                    self._loop.run_until_complete(self._task)
                finally:
                    try:
                        if self._runner:
                            self._loop.run_until_complete(self._runner.cleanup())
                    except Exception:
                        pass
                    for pc in list(self._pcs):
                        try:
                            self._loop.run_until_complete(pc.close())
                        except Exception:
                            pass
                    try:
                        self._loop.stop()
                    except Exception:
                        pass
                    try:
                        self._loop.close()
                    except Exception:
                        pass

            async def _main(self):
                if not self._aiohttp_ok:
                    parent.statusChanged.emit("aiohttp not installed. Install: pip install aiohttp")
                    parent.urlsUpdated.emit(self._local_urls())
                    await self._dummy_frames()
                    return

                from aiohttp import web

                app = web.Application()
                app.add_routes([
                    web.get('/health', self._handle_health),
                ])

                if self._aiortc_ok:
                    app.router.add_post('/whip', self._handle_whip)
                    parent.statusChanged.emit("WHIP server ready.")
                else:
                    app.router.add_post('/whip', self._handle_whip_unavailable)
                    parent.statusChanged.emit("aiortc/av not installed. Install: pip install aiortc av numpy")

                self._runner = web.AppRunner(app)
                await self._runner.setup()
                self._site = web.TCPSite(self._runner, '0.0.0.0', self._port)
                await self._site.start()

                parent.urlsUpdated.emit(self._local_urls())

                assert self._stop_event is not None
                await self._stop_event.wait()

            async def _handle_health(self, request):
                from aiohttp import web
                return web.Response(text="ok")

            async def _handle_whip_unavailable(self, request):
                from aiohttp import web
                return web.Response(status=503, text="Server missing aiortc/av dependencies.")

            async def _handle_whip(self, request):
                from aiohttp import web
                import uuid
                from aiortc import RTCPeerConnection, RTCSessionDescription
                from aiortc.contrib.media import MediaBlackhole

                if request.content_type != 'application/sdp':
                    return web.Response(status=415, text='Expected application/sdp')

                offer = await request.text()

                pc = RTCPeerConnection()
                self._pcs.add(pc)

                @pc.on("connectionstatechange")
                async def on_state_change():
                    if pc.connectionState in ("failed", "closed", "disconnected"):
                        await pc.close()
                        self._pcs.discard(pc)

                audio_sink = MediaBlackhole()

                @pc.on("track")
                def on_track(track):
                    if track.kind == "video":
                        self._loop.create_task(self._consume_video(track))
                    elif track.kind == "audio":
                        self._loop.create_task(self._consume_audio(track, audio_sink))

                await pc.setRemoteDescription(RTCSessionDescription(sdp=offer, type="offer"))
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                location = f"/resource/{uuid.uuid4()}"
                headers = {
                    'Content-Type': 'application/sdp',
                    'Location': location,
                }
                return web.Response(status=201, headers=headers, text=pc.localDescription.sdp)

            async def _consume_audio(self, track, sink):
                try:
                    while True:
                        frame = await track.recv()
                        sink.write(frame)
                except Exception:
                    pass

            async def _consume_video(self, track):
                import numpy as np  # type: ignore
                try:
                    while True:
                        frame = await track.recv()
                        arr = frame.to_ndarray(format="rgb24")
                        h, w, ch = arr.shape
                        bytes_per_line = ch * w
                        qimg = QtGui.QImage(arr.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
                        parent.frameReady.emit(qimg.copy())
                except Exception:
                    pass

            async def _dummy_frames(self):
                hue = 0
                while not self._stop_event.is_set():
                    w, h = 640, 360
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
                    painter.drawText(12, 28, f"WHIP server inactive — {ts}")
                    painter.end()
                    parent.frameReady.emit(img)
                    hue = (hue + 2) % 360
                    await asyncio.sleep(1/30)

        worker = ServerWorker(self._port)
        th = QtCore.QThread(self)
        worker.moveToThread(th)
        th.started.connect(worker.loop)
        self._worker = worker
        self._thread = th
        th.start()

