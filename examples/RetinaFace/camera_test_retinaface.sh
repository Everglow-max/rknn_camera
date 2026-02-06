#!/usr/bin/env bash

set -u

DEMO_DIR="/userdata/rknn_RetinaFace_demo"
MODEL_PATH="model/RetinaFace.rknn"
CAMERA_DEV="/dev/video0"
VIDEO_SIZE="640x480"
INTERVAL_SEC="0.2"
OUTPUT_DIR="/tmp/retinaface_results"
MAX_FRAMES="0"
KEEP_FRAMES="0"

print_help() {
  cat <<'EOF'
RetinaFace Camera Test Runner

Usage:
  ./camera_test_retinaface.sh [options]

Options:
  --demo-dir <path>      Demo directory on board (default: /userdata/rknn_RetinaFace_demo)
  --model <path>         Model path relative to demo dir or absolute path (default: model/RetinaFace.rknn)
  --camera <path>        Camera device (default: /dev/video0)
  --size <WxH>           Capture size (default: 640x480)
  --interval <seconds>   Sleep seconds between frames (default: 0.2)
  --output-dir <path>    Directory to save result images/logs (default: /tmp/retinaface_results)
  --max-frames <num>     Stop after N frames, 0 means infinite loop (default: 0)
  --keep-frames          Keep captured raw frames
  -h, --help             Show help

Examples:
  ./camera_test_retinaface.sh
  ./camera_test_retinaface.sh --camera /dev/video2 --size 1280x720 --interval 0.1
  ./camera_test_retinaface.sh --max-frames 200 --output-dir /tmp/retina_run
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --demo-dir)
      DEMO_DIR="$2"
      shift 2
      ;;
    --model)
      MODEL_PATH="$2"
      shift 2
      ;;
    --camera)
      CAMERA_DEV="$2"
      shift 2
      ;;
    --size)
      VIDEO_SIZE="$2"
      shift 2
      ;;
    --interval)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --max-frames)
      MAX_FRAMES="$2"
      shift 2
      ;;
    --keep-frames)
      KEEP_FRAMES="1"
      shift 1
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $1"
      print_help
      exit 1
      ;;
  esac
done

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[ERROR] ffmpeg not found. Install ffmpeg on board first."
  exit 1
fi

if [ ! -d "$DEMO_DIR" ]; then
  echo "[ERROR] Demo directory not found: $DEMO_DIR"
  exit 1
fi

cd "$DEMO_DIR" || exit 1

if [ ! -x "./rknn_retinaface_demo" ]; then
  echo "[ERROR] Executable not found or not executable: $DEMO_DIR/rknn_retinaface_demo"
  exit 1
fi

if [ ! -e "$MODEL_PATH" ]; then
  echo "[ERROR] Model file not found: $MODEL_PATH"
  exit 1
fi

if [ ! -e "$CAMERA_DEV" ]; then
  echo "[ERROR] Camera device not found: $CAMERA_DEV"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

export LD_LIBRARY_PATH="./lib:${LD_LIBRARY_PATH:-}"

echo "[INFO] Demo dir   : $DEMO_DIR"
echo "[INFO] Model      : $MODEL_PATH"
echo "[INFO] Camera dev : $CAMERA_DEV"
echo "[INFO] Video size : $VIDEO_SIZE"
echo "[INFO] Interval   : ${INTERVAL_SEC}s"
echo "[INFO] Output dir : $OUTPUT_DIR"
echo "[INFO] Max frames : $MAX_FRAMES (0 = infinite)"
echo "[INFO] Press Ctrl+C to stop"

frame_id=0

cleanup() {
  echo ""
  echo "[INFO] Stopped. Saved outputs in: $OUTPUT_DIR"
}

trap cleanup INT TERM

while true; do
  frame_id=$((frame_id + 1))
  ts="$(date +%Y%m%d_%H%M%S)"
  frame_path="/tmp/retinaface_cam_${frame_id}.jpg"
  log_path="$OUTPUT_DIR/log_${frame_id}.txt"
  result_path="$OUTPUT_DIR/result_${frame_id}.jpg"

  ffmpeg -hide_banner -loglevel error -f v4l2 -video_size "$VIDEO_SIZE" -i "$CAMERA_DEV" -frames:v 1 -y "$frame_path"
  if [ $? -ne 0 ]; then
    echo "[WARN] Frame ${frame_id}: capture failed"
    sleep "$INTERVAL_SEC"
    continue
  fi

  ./rknn_retinaface_demo "$MODEL_PATH" "$frame_path" >"$log_path" 2>&1
  run_ret=$?

  if [ $run_ret -ne 0 ]; then
    echo "[ERROR] Frame ${frame_id}: inference failed, see $log_path"
    break
  fi

  if [ -f "result.jpg" ]; then
    cp -f "result.jpg" "$result_path"
  fi

  face_count="$(grep -c "face @" "$log_path" 2>/dev/null || true)"
  echo "[${ts}] frame=${frame_id} faces=${face_count} result=${result_path}"

  if [ "$KEEP_FRAMES" != "1" ]; then
    rm -f "$frame_path"
  fi

  if [ "$MAX_FRAMES" != "0" ] && [ "$frame_id" -ge "$MAX_FRAMES" ]; then
    echo "[INFO] Reached max frames: $MAX_FRAMES"
    break
  fi

  sleep "$INTERVAL_SEC"
done

cleanup

