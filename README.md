# RetinaFace 详细使用教程（RK3566）

能在 RK3566 板子上完成：

1. **单张图片人脸检测**
2. **摄像头实时人脸检测（OpenCV+C++）**

> 说明：下面命令分为两类：
> 
> - **PC 端命令**：在你的 Ubuntu 主机执行
> - **板端命令**：通过 `ssh` 登录到板子后执行

---

## 1. 先准备环境（PC 端）

进入仓库根目录（例如）：

```bash
cd /home/everglow/Downloads/rknn/rknn_model_zoo
```

安装编译工具（只需一次）：

```bash
sudo apt update
sudo apt install -y gcc-aarch64-linux-gnu g++-aarch64-linux-gnu cmake make
```

检查工具是否可用：

```bash
aarch64-linux-gnu-gcc --version
cmake --version
```

---

## 2. 准备 RKNN 模型

有两种情况：

### 情况 A：已经有 `.rknn` 文件

直接用即可，后面把它复制到安装目录中。

### 情况 B：只有 ONNX，需要转换

```bash
cd examples/RetinaFace/python
python3 convert.py ../model/RetinaFace_mobile320.onnx rk3566 i8 ../model/RetinaFace.rknn
cd ../../
```

转换成功后模型位置通常是：

- `examples/RetinaFace/model/RetinaFace.rknn`

---

## 3. 编译 RetinaFace Demo（包含图片版 + 摄像头版）

在仓库根目录执行：

```bash
cd /home/everglow/Downloads/rknn/rknn_model_zoo
export GCC_COMPILER=aarch64-linux-gnu
./build-linux.sh -t rk3566 -a aarch64 -d RetinaFace
```

编译成功后，产物目录在：

- `install/rk356x_linux_aarch64/rknn_RetinaFace_demo`

你会看到两个可执行程序：

- `rknn_retinaface_demo`（单图推理）
- `rknn_retinaface_camera_demo`（摄像头推理）

---

## 4. 把模型放进安装目录（PC 端）

如果模型不是默认名字，建议统一拷贝为 `RetinaFace.rknn`：

```bash
cp /你的模型路径/xxx.rknn install/rk356x_linux_aarch64/rknn_RetinaFace_demo/model/RetinaFace.rknn
```

可检查一下：

```bash
ls -lh install/rk356x_linux_aarch64/rknn_RetinaFace_demo/model/
```

---

## 5. 用 SCP 传到板子（PC 端）

```bash
scp -r install/rk356x_linux_aarch64/rknn_RetinaFace_demo root@<板子IP>:/userdata/
```

传完后板子上目录应为：

- `/userdata/rknn_RetinaFace_demo/`

---

## 6. 单张图片推理（板端）

登录板子：

```bash
ssh root@<板子IP>
```

进入目录并设置动态库路径：

```bash
cd /userdata/rknn_RetinaFace_demo
export LD_LIBRARY_PATH=./lib:$LD_LIBRARY_PATH
```

运行单图检测：

```bash
./rknn_retinaface_demo model/RetinaFace.rknn model/test.jpg
```

成功现象：

- 终端打印 `face @ (...) score=...`
- 目录下生成结果图：`result.jpg`

---

## 7. 摄像头实时推理（板端）

先确认摄像头节点：

```bash
ls /dev/video*
```

假设摄像头是 `/dev/video0`，运行：

```bash
cd /userdata/rknn_RetinaFace_demo
export LD_LIBRARY_PATH=./lib:$LD_LIBRARY_PATH
./rknn_retinaface_camera_demo model/RetinaFace.rknn /dev/video0 640 480
```

参数含义：

```text
./rknn_retinaface_camera_demo <model_path> [camera] [width] [height]
```

例如：

- `./rknn_retinaface_camera_demo model/RetinaFace.rknn /dev/video2 1280 720`

成功现象：

- 终端每隔一段时间打印 `frame=... faces=... fps=...`
- 实时结果图持续写入：`result_camera.jpg`

停止方式：

- 按 `Ctrl+C`

---

## 8. 把结果拉回 PC（可选）

在 PC 端执行：

```bash
scp root@<板子IP>:/userdata/rknn_RetinaFace_demo/result.jpg ./
scp root@<板子IP>:/userdata/rknn_RetinaFace_demo/result_camera.jpg ./
```

---

## 9. 常见问题排查

### 1) `aarch64-linux-gnu-gcc is not available`

PC 没装交叉编译器，安装：

```bash
sudo apt install -y gcc-aarch64-linux-gnu g++-aarch64-linux-gnu
```

### 2) `cmake: command not found`

```bash
sudo apt install -y cmake make
```

### 3) `rknn_init fail`

通常是 **模型版本和板端 `librknnrt.so` 版本不匹配**。请使用同一套 RKNN Toolkit / Runtime 版本。

### 4) 摄像头打不开

- 检查设备节点：`ls /dev/video*`
- 换设备号：`/dev/video1`、`/dev/video2`
- 确认当前用户有摄像头访问权限（root 通常没问题）

### 5) 摄像头程序提示 `unsupported pixel format`

当前摄像头程序支持 `MJPEG` 和 `YUYV`。如果摄像头输出其他格式，需要切换摄像头输出格式或扩展代码。

---

## 10. 最短命令速查

### PC 端

```bash
cd /home/everglow/Downloads/rknn/rknn_model_zoo
export GCC_COMPILER=aarch64-linux-gnu
./build-linux.sh -t rk3566 -a aarch64 -d RetinaFace
cp /你的模型路径/xxx.rknn install/rk356x_linux_aarch64/rknn_RetinaFace_demo/model/RetinaFace.rknn
scp -r install/rk356x_linux_aarch64/rknn_RetinaFace_demo root@<板子IP>:/userdata/
```

### 板端

```bash
cd /userdata/rknn_RetinaFace_demo
export LD_LIBRARY_PATH=./lib:$LD_LIBRARY_PATH
./rknn_retinaface_demo model/RetinaFace.rknn model/test.jpg
./rknn_retinaface_camera_demo model/RetinaFace.rknn /dev/video0 640 480
```
