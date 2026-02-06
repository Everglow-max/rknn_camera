import os
import sys
import urllib
import urllib.request
import time
import numpy as np
import argparse
import cv2
from math import ceil
from itertools import product as product

from rknn.api import RKNN

def letterbox_resize(image, size, bg_color):
    """
    对图像进行 Letterbox 缩放（保持长宽比填充）
    :param image: 输入图像，可以是 NumPy 数组或文件路径
    :param size: 目标尺寸 (宽, 高)
    :param bg_color: 背景填充颜色 (例如 114)
    :return: 处理后的图像, 缩放比例, x偏移, y偏移
    """
    if isinstance(image, str):
        image = cv2.imread(image)

    target_width, target_height = size
    image_height, image_width, _ = image.shape

    # 计算调整后的图像尺寸，保持长宽比
    aspect_ratio = min(target_width / image_width, target_height / image_height)
    new_width = int(image_width * aspect_ratio)
    new_height = int(image_height * aspect_ratio)

    # 使用 cv2.resize() 进行等比例缩放
    image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)

    # 创建一个新的画布并填充背景色
    result_image = np.ones((target_height, target_width, 3), dtype=np.uint8) * bg_color
    
    # 计算居中贴图的偏移量
    offset_x = (target_width - new_width) // 2
    offset_y = (target_height - new_height) // 2
    
    # 将缩放后的图像复制到画布中心
    result_image[offset_y:offset_y + new_height, offset_x:offset_x + new_width] = image
    return result_image, aspect_ratio, offset_x, offset_y

def PriorBox(image_size): 
    """
    生成先验框 (Anchors)
    :param image_size: 支持输入的图像尺寸，如 (320,320) 或 (640,640)
    :return: 先验框数组
    """
    anchors = []
    # 特征图对应的最小 anchor 尺寸
    min_sizes = [[16, 32], [64, 128], [256, 512]]
    # 下采样步长 (Strides)
    steps = [8, 16, 32]
    # 计算每个层级特征图的大小
    feature_maps = [[ceil(image_size[0] / step), ceil(image_size[1] / step)] for step in steps]
    
    for k, f in enumerate(feature_maps):
        min_sizes_ = min_sizes[k]
        # 遍历特征图的每一个像素点
        for i, j in product(range(f[0]), range(f[1])):
            for min_size in min_sizes_:
                # 计算归一化的 anchor 尺寸
                s_kx = min_size / image_size[1]
                s_ky = min_size / image_size[0]
                # 计算 anchor 中心点坐标 (归一化)
                dense_cx = [x * steps[k] / image_size[1] for x in [j + 0.5]]
                dense_cy = [y * steps[k] / image_size[0] for y in [i + 0.5]]
                for cy, cx in product(dense_cy, dense_cx):
                    anchors += [cx, cy, s_kx, s_ky]
    
    output = np.array(anchors).reshape(-1, 4)
    # print("image_size:", image_size, " num_priors=", output.shape[0])
    return output

def box_decode(loc, priors):
    """
    解码边界框：利用先验框将模型预测的偏移量还原为实际坐标。
    Args:
        loc (tensor): 边界框预测层输出，形状: [num_priors, 4]
        priors (tensor): 先验框 (center-offset 格式)，形状: [num_priors, 4]
    Return:
        decoded bounding box predictions: 解码后的边界框坐标 (x_min, y_min, x_max, y_max)
    """
    # 这里的方差 (variances) 是训练时使用的超参数
    variances = [0.1, 0.2]
    
    # 公式：
    # 预测中心 = 先验中心 + 偏移量 * 方差 * 先验宽高
    # 预测宽高 = 先验宽高 * exp(偏移量 * 方差)
    boxes = np.concatenate((
        priors[:, :2] + loc[:, :2] * variances[0] * priors[:, 2:],
        priors[:, 2:] * np.exp(loc[:, 2:] * variances[1])), axis=1)
    
    # 将 (cx, cy, w, h) 转换为 (x_min, y_min, x_max, y_max)
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 2:] += boxes[:, :2]
    return boxes

def decode_landm(pre, priors):
    """
    解码人脸关键点：利用先验框将预测的偏移量还原为实际坐标。
    Args:
        pre (tensor): 关键点预测层输出，形状: [num_priors, 10] (5个点 x 2坐标)
        priors (tensor): 先验框
    Return:
        decoded landm predictions: 解码后的关键点坐标
    """
    variances = [0.1, 0.2]
    # 对 5 个关键点分别进行解码
    landmarks = np.concatenate((
        priors[:, :2] + pre[:, :2] * variances[0] * priors[:, 2:],
        priors[:, :2] + pre[:, 2:4] * variances[0] * priors[:, 2:],
        priors[:, :2] + pre[:, 4:6] * variances[0] * priors[:, 2:],
        priors[:, :2] + pre[:, 6:8] * variances[0] * priors[:, 2:],
        priors[:, :2] + pre[:, 8:10] * variances[0] * priors[:, 2:]
    ), axis=1)
    return landmarks

def nms(dets, thresh):
    """
    纯 Python 实现的非极大值抑制 (NMS) 基线代码。
    用于去除重叠度过高的冗余检测框。
    """
    x1 = dets[:, 0]
    y1 = dets[:, 1]
    x2 = dets[:, 2]
    y2 = dets[:, 3]
    scores = dets[:, 4]

    # 计算每个框的面积 (加1是为了防止除零或极小像素误差)
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    # 按置信度从高到低排序
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        # 计算当前框与其他框的交集坐标
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        # 计算交集宽高及面积
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        
        # 计算交并比 (IoU)
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        # 保留 IoU 小于阈值的框 (即去除重叠度高的框)
        inds = np.where(ovr <= thresh)[0]
        order = order[inds + 1]

    return keep

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RetinaFace Python Demo', add_help=True)
    # 基本参数
    parser.add_argument('--model_path', type=str, required=True,
                        help='模型路径，应为 .rknn 文件')
    parser.add_argument('--target', type=str,
                        default='rk3566', help='目标 RKNPU 平台 (如 rk3588, rk3566)')
    parser.add_argument('--device_id', type=str,
                        default=None, help='设备 ID (多设备连接时指定)')
    args = parser.parse_args()

    # 创建 RKNN 对象
    rknn = RKNN(verbose=True)

    # 加载 RKNN 模型
    ret = rknn.load_rknn(args.model_path)
    if ret != 0:
        print('加载 RKNN 模型 \"{}\" 失败!'.format(args.model_path))
        exit(ret)
    print('done')

    # 初始化运行环境
    print('--> 初始化运行环境')
    ret = rknn.init_runtime(target=args.target, device_id=args.device_id)
    if ret != 0:
        print('初始化运行环境失败!')
        exit(ret)
    print('done')

    # 设置输入
    img_path = '../model/test.jpg'
    if not os.path.exists(img_path):
        print(f"错误: 找不到测试图片 {img_path}")
        rknn.release()
        sys.exit(1)

    img = cv2.imread(img_path)
    img_height, img_width, _ = img.shape
    model_height, model_width = (320, 320) # 模型的输入尺寸
    
    # Letterbox 缩放：保持比例，填充灰边
    letterbox_img, aspect_ratio, offset_x, offset_y = letterbox_resize(img, (model_height, model_width), 114)
    
    # 格式转换：OpenCV 默认是 BGR，RKNN 模型需要 RGB 
    infer_img = letterbox_img[..., ::-1]  # BGR 转 RGB

    # 推理 (Inference)
    print('--> 运行模型推理')
    # inputs 列表对应模型的输入节点
    outputs = rknn.inference(inputs=[infer_img])
    
    # 获取输出：位置偏移、置信度、关键点偏移
    loc, conf, landmarks = outputs
    
    # 生成先验框
    priors = PriorBox(image_size=(model_height, model_width))
    
    # 解码边界框
    boxes = box_decode(loc.squeeze(0), priors)
    
    # 将归一化的坐标恢复到 320x320 尺度
    scale = np.array([model_width, model_height,
                      model_width, model_height])
    boxes = boxes * scale // 1  # 得到在 letterbox 图上的 face box
    
    # 将 letterbox 坐标映射回原图坐标
    # 公式：(x_letterbox - offset) / ratio
    boxes[..., 0::2] = np.clip((boxes[..., 0::2] - offset_x) / aspect_ratio, 0, img_width)  
    boxes[..., 1::2] = np.clip((boxes[..., 1::2] - offset_y) / aspect_ratio, 0, img_height) 
    
    # 获取人脸置信度分数 (通常 index 1 是正类 'face' 的概率)
    scores = conf.squeeze(0)[:, 1] 
    
    # 解码人脸关键点数据
    landmarks = decode_landm(landmarks.squeeze(0), priors)
    
    # 将关键点恢复到 320x320 尺度
    scale_landmarks = np.array([model_width, model_height, model_width, model_height,
                                model_width, model_height, model_width, model_height,
                                model_width, model_height])
    landmarks = landmarks * scale_landmarks // 1
    
    # 将关键点映射回原图坐标
    landmarks[..., 0::2] = np.clip((landmarks[..., 0::2] - offset_x) / aspect_ratio, 0, img_width) 
    landmarks[..., 1::2] = np.clip((landmarks[..., 1::2] - offset_y) / aspect_ratio, 0, img_height) 
    
    # 忽略低置信度的检测结果
    inds = np.where(scores > 0.02)[0]
    boxes = boxes[inds]
    landmarks = landmarks[inds]
    scores = scores[inds]

    # 排序：按置信度从高到低
    order = scores.argsort()[::-1]
    boxes = boxes[order]
    landmarks = landmarks[order]
    scores = scores[order]

    # 执行 NMS (非极大值抑制)
    dets = np.hstack((boxes, scores[:, np.newaxis])).astype(np.float32, copy=False)
    keep = nms(dets, 0.4) # 阈值通常设为 0.4 或 0.5
    dets = dets[keep, :]
    landmarks = landmarks[keep]
    
    # 合并 box 和 landmarks 数据以便遍历绘制
    dets = np.concatenate((dets, landmarks), axis=1)

    # 遍历检测结果并绘图
    for data in dets:
        if data[4] < 0.5: # 最终可视化阈值
            continue
            
        print("发现人脸 @ (%d %d %d %d) 置信度: %f" % (data[0], data[1], data[2], data[3], data[4]))
        text = "{:.4f}".format(data[4])
        data = list(map(int, data))
        
        # 绘制矩形框
        cv2.rectangle(img, (data[0], data[1]),
                      (data[2], data[3]), (0, 0, 255), 2)
        cx = data[0]
        cy = data[1] + 12
        cv2.putText(img, text, (cx, cy),
                    cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 255, 255))
        
        # 绘制 5 个关键点 (红、黄、粉、绿、蓝)
        cv2.circle(img, (data[5], data[6]), 1, (0, 0, 255), 5)  # 左眼
        cv2.circle(img, (data[7], data[8]), 1, (0, 255, 255), 5)  # 右眼
        cv2.circle(img, (data[9], data[10]), 1, (255, 0, 255), 5) # 鼻子
        cv2.circle(img, (data[11], data[12]), 1, (0, 255, 0), 5)  # 左嘴角
        cv2.circle(img, (data[13], data[14]), 1, (255, 0, 0), 5)  # 右嘴角
        
    img_save_path = './result.jpg'
    cv2.imwrite(img_save_path, img)
    print("结果图像已保存至", img_save_path)
    
    # 释放资源
    rknn.release()