#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从远程 OSS 的 mp4 视频资源截取第一帧为图片。
支持：HTTP(S) URL、本地文件路径。
"""

import os
import sys
import tempfile
import argparse

try:
    import requests
    from moviepy import VideoFileClip
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)


def download_from_url(url, save_path, timeout=60):
    """从 URL 下载文件到本地路径。"""
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def capture_first_frame(source, output_path=None, format="png"):
    """
    截取视频第一帧。
    :param source: 视频来源，可为 HTTP(S) URL 或本地文件路径
    :param output_path: 输出图片路径，不传则根据 source 自动生成
    :param format: 图片格式，如 png、jpg
    :return: 输出图片的绝对路径
    """
    is_url = source.startswith("http://") or source.startswith("https://")
    temp_path = None

    try:
        if is_url:
            fd, temp_path = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            download_from_url(source, temp_path)
            video_path = temp_path
        else:
            if not os.path.isfile(source):
                raise FileNotFoundError("本地文件不存在: {}".format(source))
            video_path = source

        if output_path is None:
            base = os.path.splitext(os.path.basename(video_path))[0]
            if not base or base.endswith(".mp4"):
                base = "frame"
            output_path = base + "_first_frame." + format.lstrip(".")

        clip = VideoFileClip(video_path)
        clip.save_frame(output_path, t=0)
        clip.close()
        return os.path.abspath(output_path)
    finally:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="从远程 OSS 或本地 mp4 截取第一帧")
    parser.add_argument("source", help="视频 URL 或本地文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出图片路径（默认自动生成）")
    parser.add_argument("-f", "--format", default="png", help="图片格式，如 png、jpg（默认 png）")
    args = parser.parse_args()

    try:
        out = capture_first_frame(args.source, args.output, args.format)
        print("第一帧已保存: {}".format(out))
    except Exception as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
