import cv2
import os
import time

class VideoProcessor:
    """
    视频处理工具类，用于从视频中抽取图像帧生成数据集。
    """
    
    @staticmethod
    def extract_frames(video_path: str, output_dir: str, mode: str = 'count', value: float = 100, callback=None):
        """
        从视频中抽取帧
        :param video_path: 视频文件路径
        :param output_dir: 保存图片的目录
        :param mode: 'count' (指定总张数) 或 'interval' (指定时间间隔，秒)
        :param value: 对应的数值
        :param callback: 进度回调函数 callback(current, total)
        :return: (success, message)
        """
        if not os.path.exists(video_path):
            return False, "视频文件不存在"
        
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                return False, f"创建目录失败: {e}"

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False, "无法打开视频文件"

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        if total_frames <= 0:
            return False, "视频内容为空"

        # 计算需要抽取的帧索引列表
        frame_indices = []
        if mode == 'count':
            count = int(value)
            if count <= 0: return False, "抽取张数必须大于 0"
            step = max(1, total_frames // count)
            frame_indices = [i * step for i in range(min(count, total_frames // step))]
        else: # interval
            interval_s = float(value)
            if interval_s <= 0: return False, "时间间隔必须大于 0"
            step = int(fps * interval_s)
            if step <= 0: step = 1
            frame_indices = [i for i in range(0, total_frames, step)]

        actual_total = len(frame_indices)
        success_count = 0
        
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        for i, idx in enumerate(frame_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                img_name = f"{video_name}_frame_{idx:08d}.jpg"
                img_path = os.path.join(output_dir, img_name)
                cv2.imwrite(img_path, frame)
                success_count += 1
            
            if callback:
                callback(i + 1, actual_total)

        cap.release()
        return True, f"抽取完成，成功保存 {success_count} 张图片至 {output_dir}"
