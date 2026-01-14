import os

class YOLOHelper:
    """
    处理 YOLO 格式的读写与坐标转换
    格式：class_id x_center y_center width height (均为归一化 0-1)
    """
    
    @staticmethod
    def pixel_to_yolo(pixel_box, img_w, img_h):
        """像素坐标 [x, y, w, h] -> YOLO 归一化格式"""
        if not img_w or not img_h:
            return [0, 0, 0, 0]
        x, y, w, h = pixel_box[:4]
        x_center = (x + w / 2) / img_w
        y_center = (y + h / 2) / img_h
        nw = w / img_w
        nh = h / img_h
        return [x_center, y_center, nw, nh]

    @staticmethod
    def yolo_to_pixel(yolo_box, img_w, img_h):
        """YOLO 归一化格式 -> 像素坐标 [x, y, w, h]"""
        if not img_w or not img_h:
            return [0, 0, 0, 0]
        xc, yc, nw, nh = yolo_box[:4]
        w = nw * img_w
        h = nh * img_h
        x = xc * img_w - w / 2
        y = yc * img_h - h / 2
        return [int(x), int(y), int(w), int(h)]

    @staticmethod
    def load_labels(label_path, img_w, img_h):
        """从 .txt 文件读取标签"""
        boxes = []
        if not os.path.exists(label_path):
            return boxes
            
        try:
            with open(label_path, 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        class_id = int(parts[0])
                        yolo_box = [float(x) for x in parts[1:]]
                        pixel_box = YOLOHelper.yolo_to_pixel(yolo_box, img_w, img_h)
                        boxes.append(pixel_box + [class_id])
        except Exception as e:
            print(f"读取标签失败: {e}")
        return boxes

    @staticmethod
    def save_labels(label_path, boxes, img_w, img_h):
        """保存标签到 .txt 文件"""
        if not img_w or not img_h:
            return False
        try:
            with open(label_path, 'w') as f:
                for box in boxes:
                    if len(box) < 4:
                        continue
                    pixel_box = box[:4]
                    class_id = box[4] if len(box) > 4 else 0
                    yolo_box = YOLOHelper.pixel_to_yolo(pixel_box, img_w, img_h)
                    line = f"{class_id} " + " ".join([f"{x:.6f}" for x in yolo_box]) + "\n"
                    f.write(line)
            return True
        except Exception as e:
            print(f"保存标签失败: {e}")
            return False
