from ultralytics import YOLO


def main() -> None:
    model = YOLO("yolo26n-seg.pt")
    model.train(data="training/lane_seg.yaml", epochs=80, imgsz=416, batch=8, device=0)
    model.export(format="ncnn", imgsz=416, batch=1)


if __name__ == "__main__":
    main()
