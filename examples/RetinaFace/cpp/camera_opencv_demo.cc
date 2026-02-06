#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <string>
#include <vector>

#include <linux/videodev2.h>

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include "retinaface.h"

static volatile sig_atomic_t g_should_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_should_stop = 1;
}

static bool is_integer_string(const std::string &text)
{
    if (text.empty()) {
        return false;
    }
    size_t start = 0;
    if (text[0] == '+' || text[0] == '-') {
        if (text.size() == 1) {
            return false;
        }
        start = 1;
    }
    for (size_t i = start; i < text.size(); ++i) {
        if (text[i] < '0' || text[i] > '9') {
            return false;
        }
    }
    return true;
}

struct V4L2Buffer {
    void *start;
    size_t length;
};

struct V4L2Camera {
    int fd;
    std::vector<V4L2Buffer> buffers;
    uint32_t pixel_format;
    int width;
    int height;
};

static int open_camera(V4L2Camera *cam, const std::string &camera_dev, int width, int height)
{
    memset(cam, 0, sizeof(*cam));
    cam->fd = -1;

    cam->fd = open(camera_dev.c_str(), O_RDWR | O_NONBLOCK, 0);
    if (cam->fd < 0) {
        printf("open camera failed: %s, errno=%d\n", camera_dev.c_str(), errno);
        return -1;
    }

    struct v4l2_capability cap;
    memset(&cap, 0, sizeof(cap));
    if (ioctl(cam->fd, VIDIOC_QUERYCAP, &cap) < 0) {
        printf("VIDIOC_QUERYCAP failed\n");
        return -1;
    }

    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;

    if (ioctl(cam->fd, VIDIOC_S_FMT, &fmt) < 0) {
        printf("VIDIOC_S_FMT(MJPEG) failed\n");
        return -1;
    }

    cam->pixel_format = fmt.fmt.pix.pixelformat;
    cam->width = fmt.fmt.pix.width;
    cam->height = fmt.fmt.pix.height;

    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = 4;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;

    if (ioctl(cam->fd, VIDIOC_REQBUFS, &req) < 0 || req.count < 2) {
        printf("VIDIOC_REQBUFS failed\n");
        return -1;
    }

    cam->buffers.resize(req.count);
    for (uint32_t i = 0; i < req.count; ++i) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;

        if (ioctl(cam->fd, VIDIOC_QUERYBUF, &buf) < 0) {
            printf("VIDIOC_QUERYBUF failed index=%u\n", i);
            return -1;
        }

        cam->buffers[i].length = buf.length;
        cam->buffers[i].start = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, cam->fd, buf.m.offset);
        if (cam->buffers[i].start == MAP_FAILED) {
            printf("mmap failed index=%u\n", i);
            return -1;
        }
    }

    for (uint32_t i = 0; i < req.count; ++i) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (ioctl(cam->fd, VIDIOC_QBUF, &buf) < 0) {
            printf("VIDIOC_QBUF failed index=%u\n", i);
            return -1;
        }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(cam->fd, VIDIOC_STREAMON, &type) < 0) {
        printf("VIDIOC_STREAMON failed\n");
        return -1;
    }

    return 0;
}

static void close_camera(V4L2Camera *cam)
{
    if (cam->fd >= 0) {
        enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        ioctl(cam->fd, VIDIOC_STREAMOFF, &type);
    }

    for (size_t i = 0; i < cam->buffers.size(); ++i) {
        if (cam->buffers[i].start != NULL && cam->buffers[i].start != MAP_FAILED) {
            munmap(cam->buffers[i].start, cam->buffers[i].length);
        }
    }
    cam->buffers.clear();

    if (cam->fd >= 0) {
        close(cam->fd);
        cam->fd = -1;
    }
}

static int read_camera_frame(V4L2Camera *cam, std::vector<uint8_t> *out_bytes, int timeout_ms)
{
    struct pollfd pfd;
    pfd.fd = cam->fd;
    pfd.events = POLLIN;

    int pret = poll(&pfd, 1, timeout_ms);
    if (pret <= 0) {
        return -1;
    }

    struct v4l2_buffer buf;
    memset(&buf, 0, sizeof(buf));
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;

    if (ioctl(cam->fd, VIDIOC_DQBUF, &buf) < 0) {
        if (errno == EAGAIN) {
            return -1;
        }
        return -1;
    }

    out_bytes->resize(buf.bytesused);
    memcpy(out_bytes->data(), cam->buffers[buf.index].start, buf.bytesused);

    if (ioctl(cam->fd, VIDIOC_QBUF, &buf) < 0) {
        return -1;
    }

    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("%s <model_path> [camera(/dev/video0|0)] [width] [height]\n", argv[0]);
        printf("Example: %s model/RetinaFace.rknn /dev/video0 640 480\n", argv[0]);
        return -1;
    }

    const char *model_path = argv[1];
    std::string camera_src = (argc > 2) ? argv[2] : "0";
    int frame_width = (argc > 3) ? atoi(argv[3]) : 640;
    int frame_height = (argc > 4) ? atoi(argv[4]) : 480;

    if (is_integer_string(camera_src)) {
        camera_src = "/dev/video" + camera_src;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    rknn_app_context_t app_ctx;
    memset(&app_ctx, 0, sizeof(app_ctx));
    int ret = init_retinaface_model(model_path, &app_ctx);
    if (ret != 0) {
        printf("init_retinaface_model failed, ret=%d, model=%s\n", ret, model_path);
        return -1;
    }

    V4L2Camera camera;
    if (open_camera(&camera, camera_src, frame_width, frame_height) != 0) {
        printf("open camera failed: %s\n", camera_src.c_str());
        release_retinaface_model(&app_ctx);
        return -1;
    }

    printf("camera opened: %s\n", camera_src.c_str());
    printf("camera format: %c%c%c%c, size=%dx%d\n",
           camera.pixel_format & 0xFF,
           (camera.pixel_format >> 8) & 0xFF,
           (camera.pixel_format >> 16) & 0xFF,
           (camera.pixel_format >> 24) & 0xFF,
           camera.width, camera.height);
    printf("press Ctrl+C to stop\n");

    int frame_id = 0;
    const int64 t0 = cv::getTickCount();

    while (!g_should_stop) {
        std::vector<uint8_t> raw_bytes;
        if (read_camera_frame(&camera, &raw_bytes, 1000) != 0) {
            continue;
        }

        cv::Mat frame_bgr;
        if (camera.pixel_format == V4L2_PIX_FMT_MJPEG) {
            cv::Mat encoded(1, (int)raw_bytes.size(), CV_8UC1, raw_bytes.data());
            frame_bgr = cv::imdecode(encoded, cv::IMREAD_COLOR);
        } else if (camera.pixel_format == V4L2_PIX_FMT_YUYV) {
            cv::Mat yuyv(camera.height, camera.width, CV_8UC2, raw_bytes.data());
            cv::cvtColor(yuyv, frame_bgr, cv::COLOR_YUV2BGR_YUYV);
        } else {
            printf("unsupported pixel format in this demo\n");
            break;
        }

        if (frame_bgr.empty()) {
            continue;
        }

        cv::Mat frame_rgb;
        cv::cvtColor(frame_bgr, frame_rgb, cv::COLOR_BGR2RGB);

        image_buffer_t src_image;
        memset(&src_image, 0, sizeof(src_image));
        src_image.width = frame_rgb.cols;
        src_image.height = frame_rgb.rows;
        src_image.width_stride = frame_rgb.cols;
        src_image.height_stride = frame_rgb.rows;
        src_image.format = IMAGE_FORMAT_RGB888;
        src_image.virt_addr = frame_rgb.data;
        src_image.size = frame_rgb.cols * frame_rgb.rows * 3;
        src_image.fd = 0;

        retinaface_result result;
        memset(&result, 0, sizeof(result));
        ret = inference_retinaface_model(&app_ctx, &src_image, &result);
        if (ret != 0) {
            printf("inference_retinaface_model failed, ret=%d\n", ret);
            break;
        }

        for (int i = 0; i < result.count; ++i) {
            const int x1 = result.object[i].box.left;
            const int y1 = result.object[i].box.top;
            const int x2 = result.object[i].box.right;
            const int y2 = result.object[i].box.bottom;
            const float score = result.object[i].score;

            cv::rectangle(frame_bgr, cv::Point(x1, y1), cv::Point(x2, y2), cv::Scalar(0, 255, 0), 2);
            char score_text[32];
            snprintf(score_text, sizeof(score_text), "%.2f", score);
            cv::putText(frame_bgr, score_text, cv::Point(x1, y1 > 10 ? y1 - 5 : y1 + 15),
                        cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(0, 0, 255), 1);

            for (int j = 0; j < 5; ++j) {
                int px = result.object[i].ponit[j].x;
                int py = result.object[i].ponit[j].y;
                cv::circle(frame_bgr, cv::Point(px, py), 2, cv::Scalar(0, 165, 255), -1);
            }
        }

        frame_id++;
        const int64 now = cv::getTickCount();
        const double elapsed = (now - t0) / cv::getTickFrequency();
        const double fps = (elapsed > 0.0) ? (frame_id / elapsed) : 0.0;

        char info_text[64];
        snprintf(info_text, sizeof(info_text), "faces=%d fps=%.2f", result.count, fps);
        cv::putText(frame_bgr, info_text, cv::Point(10, 30),
                    cv::FONT_HERSHEY_SIMPLEX, 0.8, cv::Scalar(255, 255, 0), 2);

        if (frame_id % 10 == 0) {
            printf("frame=%d faces=%d fps=%.2f\n", frame_id, result.count, fps);
        }

        cv::imwrite("result_camera.jpg", frame_bgr);
    }

    close_camera(&camera);

    ret = release_retinaface_model(&app_ctx);
    if (ret != 0) {
        printf("release_retinaface_model failed, ret=%d\n", ret);
    }

    return 0;
}
