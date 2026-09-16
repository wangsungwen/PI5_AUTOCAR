from ultralytics import YOLO


def main() -> None:
    model = YOLO("yolo26n.pt")
    model.train(data="training/traffic_light.yaml", epochs=60, imgsz=416, batch=16, device=0)
    model.export(format="ncnn", imgsz=416, batch=1)


if __name__ == "__main__":
    main()
