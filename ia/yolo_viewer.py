import os, sys
from pathlib import Path
import numpy as np
from ultralytics import YOLO
from PySide6 import QtCore, QtWidgets, QtGui

try:
    import cv2
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

def qimage_from_bgr(bgr: np.ndarray) -> QtGui.QImage:
    rgb = bgr[..., ::-1].copy()
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
    return qimg.copy()

def draw_boxes_qimage(qimg: QtGui.QImage, result, names: dict) -> QtGui.QImage:
    out = qimg.copy()
    painter = QtGui.QPainter(out)
    pen_box = QtGui.QPen(QtGui.QColor("#2e8bff")); pen_box.setWidth(2)
    painter.setPen(pen_box)
    font = painter.font(); font.setPointSize(10); painter.setFont(font)
    metrics = QtGui.QFontMetrics(font)

    W, H = out.width(), out.height()
    pad = 2
    occupied: list[QtCore.QRectF] = []

    def clamp_rect(x, y, w, h):
        x = max(0.0, min(float(W - w), float(x)))
        y = max(0.0, min(float(H - h), float(y)))
        return QtCore.QRectF(x, y, float(w), float(h))

    def inter_area(a: QtCore.QRectF, b: QtCore.QRectF) -> float:
        ix1 = max(a.left(),  b.left())
        iy1 = max(a.top(),   b.top())
        ix2 = min(a.right(), b.right())
        iy2 = min(a.bottom(),b.bottom())
        return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)

    def place_label(x1, y1, x2, y2, tw, th) -> QtCore.QRectF:
        cx = (x1 + x2) * 0.5
        candidates = [
            (x1, y1 - th - pad),
            (x2 - tw, y1 - th - pad),
            (cx - tw/2, y1 - th - pad),
            (x1, y2 + pad),
            (x2 - tw, y2 + pad),
            (cx - tw/2, y2 + pad),
            (x1 - tw - pad, (y1 + y2 - th)/2),
            (x2 + pad, (y1 + y2 - th)/2),
        ]

        best_rect = None
        best_overlap = float("inf")

        for (px, py) in candidates:
            r = clamp_rect(px, py, tw, th)
            if all(r.intersects(o) is False for o in occupied):
                return r
            overlap = sum(inter_area(r, o) for o in occupied)
            if overlap < best_overlap:
                best_overlap, best_rect = overlap, r

        return best_rect if best_rect is not None else clamp_rect(x1, max(0, y1 - th - pad), tw, th)

    boxes = result.boxes
    if boxes is not None and len(boxes) > 0:
        xyxy = boxes.xyxy.cpu().numpy()
        cls  = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else None
        conf = boxes.conf.cpu().numpy() if boxes.conf is not None else None

        order = np.argsort(xyxy[:,1])
        for i in order:
            x1, y1, x2, y2 = [float(v) for v in xyxy[i]]

            painter.setPen(pen_box)
            painter.drawRect(QtCore.QRectF(x1, y1, x2 - x1, y2 - y1))

            label = names.get(cls[i], str(cls[i])) if cls is not None else "obj"
            if conf is not None:
                label = f"{label} {conf[i]:.2f}"
            tw = metrics.horizontalAdvance(label) + 10
            th = metrics.height() + 6

            bg = place_label(x1, y1, x2, y2, tw, th)
            occupied.append(bg)

            painter.fillRect(bg, QtGui.QColor(0, 0, 0, 190))
            painter.setPen(QtGui.QPen(QtCore.Qt.white))
            painter.drawText(bg.adjusted(5, 0, -3, -2),
                             QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                             label)

            painter.setPen(pen_box)

    painter.end()
    return out

class ImageLabel(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background:#0f1116;border:1px solid #2a2f3a;border-radius:8px;")
        self.pix = None

    def set_qimage(self, qimg: QtGui.QImage):
        self.pix = QtGui.QPixmap.fromImage(qimg)
        self._update_scaled()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_scaled()

    def _update_scaled(self):
        if self.pix:
            scaled = self.pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.setPixmap(scaled)

class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLOv8 viewer (head/body)")
        self.setMinimumSize(900, 700)

        self.model: YOLO | None = None
        self.image_path: Path | None = None
        self.current_qimg: QtGui.QImage | None = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        ctl = QtWidgets.QHBoxLayout()
        self.modelEdit = QtWidgets.QLineEdit()
        self.modelEdit.setPlaceholderText("weights path (e.g., runs/detect/train/weights/best.pt)")
        self.browseModelBtn = QtWidgets.QPushButton("Load weights…")
        self.openImgBtn = QtWidgets.QPushButton("Open image…")
        self.runBtn = QtWidgets.QPushButton("Detect")
        self.runBtn.setEnabled(False)

        self.deviceCombo = QtWidgets.QComboBox()
        self.deviceCombo.addItems(["cpu"])
        self.imgszSpin = QtWidgets.QSpinBox(); self.imgszSpin.setRange(320, 1536); self.imgszSpin.setValue(768)
        self.confSpin = QtWidgets.QDoubleSpinBox(); self.confSpin.setRange(0.01, 0.99); self.confSpin.setSingleStep(0.01); self.confSpin.setValue(0.25)
        ctl.addWidget(QtWidgets.QLabel("weights:")); ctl.addWidget(self.modelEdit, 1); ctl.addWidget(self.browseModelBtn)
        ctl.addSpacing(12)
        ctl.addWidget(QtWidgets.QLabel("imgsz:")); ctl.addWidget(self.imgszSpin)
        ctl.addWidget(QtWidgets.QLabel("conf:")); ctl.addWidget(self.confSpin)
        ctl.addWidget(QtWidgets.QLabel("device:")); ctl.addWidget(self.deviceCombo)
        ctl.addSpacing(12)
        ctl.addWidget(self.openImgBtn)
        ctl.addWidget(self.runBtn)

        v.addLayout(ctl)

        self.view = ImageLabel()
        v.addWidget(self.view, 1)

        self.status = self.statusBar()
        self.status.showMessage("Load weights, then open an image.")

        self.browseModelBtn.clicked.connect(self.on_load_model)
        self.openImgBtn.clicked.connect(self.on_open_image)
        self.runBtn.clicked.connect(self.on_run)

        self.setStyleSheet("""
            * { font-family:'Segoe UI', sans-serif; font-size:12px; color:#e6e6e6; }
            QMainWindow { background:#101217; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#1c1f27; border:1px solid #2a2f3a; border-radius:6px; padding:4px 6px; }
            QPushButton { background:#1c1f27; border:1px solid #2a2f3a; border-radius:8px; padding:8px 12px; }
            QPushButton:hover { background:#242935; }
            QLabel { color:#e6e6e6; }
        """)

    def on_load_model(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select YOLO weights", "", "PyTorch Weights (*.pt)")
        if not path:
            return
        self.modelEdit.setText(path)
        self.status.showMessage("Loading weights…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.model = YOLO(path)
            self.status.showMessage(f"Loaded: {os.path.basename(path)} (classes: {self.model.names})")
            self.runBtn.setEnabled(self.image_path is not None)
        except Exception as e:
            self.model = None
            QtWidgets.QMessageBox.critical(self, "Load error", str(e))
            self.status.showMessage("Failed to load weights.")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def on_open_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select image", "", "Images (*.jpg *.jpeg *.png *.bmp)")
        if not path:
            return
        self.image_path = Path(path)
        qimg = QtGui.QImage(str(self.image_path))
        if qimg.isNull():
            QtWidgets.QMessageBox.warning(self, "Open image", "Could not load image.")
            return
        self.current_qimg = qimg
        self.view.set_qimage(qimg)
        self.status.showMessage(f"Image loaded: {self.image_path.name}")
        self.runBtn.setEnabled(self.model is not None)

    def on_run(self):
        if not (self.model and self.image_path and self.current_qimg):
            return
        imgsz = int(self.imgszSpin.value())
        conf = float(self.confSpin.value())
        device = self.deviceCombo.currentText()

        self.status.showMessage("Running detection…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            results = self.model.predict(
                source=str(self.image_path),
                device=device,
                imgsz=imgsz,
                conf=conf,
                save=False,
                verbose=False
            )
            r = results[0]
            qimg = draw_boxes_qimage(self.current_qimg, r, self.model.names)
            self.view.set_qimage(qimg)
            self.status.showMessage(
                f"Done. {len(r.boxes) if r.boxes is not None else 0} objects — classes: {self.model.names}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Detection error", str(e))
            self.status.showMessage("Detection failed.")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
