from ultralytics import YOLO

model = YOLO(r"runs/detect/train/weights/best.pt")
model.train(
    data="headbody.yaml",
    epochs=50,
    imgsz=640,
    batch=8,
    device="cpu",
    cos_lr=True,
    project="runs/detect",
    name="train2"
)