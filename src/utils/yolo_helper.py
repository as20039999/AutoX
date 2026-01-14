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

    @staticmethod
    def optimize_dataset(source_dir, target_dir, imgsz=640, progress_callback=None):
        """
        优化小目标数据集：裁剪出以标注框为中心的 imgsz x imgsz 区域。
        """
        import cv2
        import numpy as np
        import shutil

        # 1. 扫描源目录
        img_exts = ('.jpg', '.jpeg', '.png')
        try:
            images = [f for f in os.listdir(source_dir) if f.lower().endswith(img_exts)]
        except Exception as e:
            print(f"扫描目录失败: {e}")
            return False
            
        if not images:
            return False
            
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        total = len(images)
        count = 0

        for img_name in images:
            img_path = os.path.join(source_dir, img_name)
            base_name = os.path.splitext(img_name)[0]
            label_name = base_name + ".txt"
            label_path = os.path.join(source_dir, label_name)

            if not os.path.exists(label_path):
                count += 1
                continue

            # 读取原图和标签
            img = cv2.imread(img_path)
            if img is None: 
                count += 1
                continue
            h, w = img.shape[:2]
            
            boxes = YOLOHelper.load_labels(label_path, w, h)
            if not boxes: 
                count += 1
                continue

            # 计算所有框的中心点
            centers = []
            for box in boxes:
                xc = box[0] + box[2] / 2
                yc = box[1] + box[3] / 2
                centers.append((xc, yc))
            
            avg_xc = int(np.mean([c[0] for c in centers]))
            avg_yc = int(np.mean([c[1] for c in centers]))

            # 确定裁剪区域 (imgsz x imgsz)
            x1 = max(0, avg_xc - imgsz // 2)
            y1 = max(0, avg_yc - imgsz // 2)
            x2 = min(w, x1 + imgsz)
            y2 = min(h, y1 + imgsz)

            # 修正 x1, y1 以确保裁剪区域是 imgsz x imgsz (如果可能)
            if x2 - x1 < imgsz: x1 = max(0, x2 - imgsz)
            if y2 - y1 < imgsz: y1 = max(0, y2 - imgsz)
            
            # 执行裁剪
            crop_img = img[y1:y2, x1:x2]
            new_h, new_w = crop_img.shape[:2]

            # 调整标签坐标并过滤
            new_boxes = []
            for box in boxes:
                bx, by, bw, bh, cid = box
                nbx = bx - x1
                nby = by - y1
                
                # 检查是否在裁剪区域内
                inter_x1 = max(0, nbx)
                inter_y1 = max(0, nby)
                inter_x2 = min(new_w, nbx + bw)
                inter_y2 = min(new_h, nby + bh)
                
                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                    # 只要有一部分在裁剪区域内就保留
                    new_boxes.append([inter_x1, inter_y1, inter_x2 - inter_x1, inter_y2 - inter_y1, cid])

            if new_boxes:
                # 保存新图和新标签
                cv2.imwrite(os.path.join(target_dir, img_name), crop_img)
                YOLOHelper.save_labels(os.path.join(target_dir, label_name), new_boxes, new_w, new_h)

            count += 1
            if progress_callback:
                progress_callback(int(count / total * 100))

        return True
