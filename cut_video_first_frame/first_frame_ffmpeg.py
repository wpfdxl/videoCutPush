#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高效截取 MP4 第一帧（依赖系统 ffmpeg）。"""

import os
import sys
import subprocess
import tempfile
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(BASE_DIR, "tmp")

try:
    import requests
except ImportError:
    requests = None


def download_from_url(url, save_path, timeout=60):
    """从 URL 下载到 save_path。"""
    if not requests:
        raise RuntimeError("从 URL 下载需安装: pip install requests")
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)


def capture_first_frame_ffmpeg(video_path, output_path, format="png", ffmpeg_cmd="ffmpeg"):
    args = [
        ffmpeg_cmd,
        "-y",
        "-i", video_path,
        "-vframes", "1",
    ]
    if format.lower() == "jpg" or output_path.lower().endswith(".jpg"):
        args.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])
    args.extend(["-q:v", "2", output_path])
    result = subprocess.run(
        args,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError("ffmpeg 执行失败: {}".format(stderr.strip() or result.returncode))
    return os.path.abspath(output_path)


def capture_first_frame(source, output_path=None, format="png", ffmpeg_cmd="ffmpeg"):
    ext = "png" if format.lower() not in ("jpg", "jpeg") else "jpg"
    is_url = source.startswith("http://") or source.startswith("https://")
    temp_path = None
    os.makedirs(TMP_DIR, exist_ok=True)

    try:
        if is_url:
            fd, temp_path = tempfile.mkstemp(suffix=".mp4", dir=TMP_DIR)
            os.close(fd)
            download_from_url(source, temp_path)
            video_path = temp_path
        else:
            if not os.path.isfile(source):
                raise FileNotFoundError("本地文件不存在: {}".format(source))
            video_path = source

        if output_path is None:
            if is_url:
                base = os.path.splitext(os.path.basename(source.split("?")[0].rstrip("/")))[0]
            else:
                base = os.path.splitext(os.path.basename(video_path))[0]
            if not base or base.endswith(".mp4"):
                base = "frame"
            output_path = os.path.join(TMP_DIR, base + "_first_frame." + ext)
        else:
            output_path = output_path.rstrip()

        return capture_first_frame_ffmpeg(video_path, output_path, format=ext, ffmpeg_cmd=ffmpeg_cmd)
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="高效截取 MP4 第一帧（依赖系统 ffmpeg）"
    )
    parser.add_argument("source", help="视频 URL 或本地文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出图片路径（默认自动生成）")
    parser.add_argument("-f", "--format", default="png", help="图片格式 png|jpg（默认 png）")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg 可执行路径（默认 ffmpeg）")
    args = parser.parse_args()

    try:
        out = capture_first_frame(
            args.source,
            output_path=args.output,
            format=args.format,
            ffmpeg_cmd=args.ffmpeg,
        )
        print("第一帧已保存: {}".format(out))
    except FileNotFoundError as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("错误: ffmpeg 执行超时", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
