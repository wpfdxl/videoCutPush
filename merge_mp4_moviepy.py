#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 mapbinlist.txt 读取视频列表（格式同 ffmpeg concat：每行 file 'path' 或 file 'url'），
按顺序合并并压缩输出为一个 mp4。清晰度可降低以减小体积，不丢帧（保持原 fps 逐帧编码）。
"""

import os
import sys
import tempfile
import argparse
import shutil

try:
    import requests
    from moviepy import VideoFileClip, concatenate_videoclips
except ImportError:
    print("请先安装依赖: pip install -r requirements.txt")
    sys.exit(1)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(BASE_DIR, "tmp")
DEFAULT_LIST_PATH = os.path.join(BASE_DIR, "mapbinlist.txt")


def parse_concat_list(list_path):
    """
    解析 concat 列表文件，每行格式：file 'path' 或 file "path" 或 file path。
    返回路径/URL 列表（已去掉引号）。
    """
    with open(list_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    paths = []
    for ln in lines:
        if not ln.startswith("file "):
            continue
        rest = ln[5:].strip()
        if (rest.startswith("'") and rest.endswith("'")) or (rest.startswith('"') and rest.endswith('"')):
            rest = rest[1:-1]
        if rest:
            paths.append(rest)
    return paths


def download_from_url(url, save_path, timeout=120):
    """从 URL 下载文件到本地路径。"""
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def resolve_path(item, temp_dir):
    """若为 URL 则下载到 temp_dir 并返回本地路径，否则校验本地文件存在后返回。"""
    if item.startswith("http://") or item.startswith("https://"):
        name = os.path.basename(item.split("?")[0]) or "video_{}.mp4".format(abs(hash(item)) % 100000)
        local_path = os.path.join(temp_dir, name)
        download_from_url(item, local_path)
        return local_path
    if not os.path.isfile(item):
        raise FileNotFoundError("本地文件不存在: {}".format(item))
    return item


def merge_mp4_from_list(
    list_path,
    output_path,
    bitrate="800k",
    audio_bitrate="128k",
    temp_dir=None,
):
    """
    从列表文件读取视频，合并并压缩输出。不丢帧（保持各段原 fps，逐帧编码）。
    :param list_path: 列表文件路径（每行 file 'path_or_url'）
    :param output_path: 输出 mp4 路径
    :param bitrate: 视频码率，越小体积越小、清晰度越低，如 800k、500k
    :param audio_bitrate: 音频码率
    :param temp_dir: 下载远程文件用的临时目录，不传则自动创建并清理
    :return: 输出文件的绝对路径
    """
    if not os.path.isfile(list_path):
        raise FileNotFoundError("列表文件不存在: {}".format(list_path))

    paths = parse_concat_list(list_path)
    if not paths:
        raise ValueError(
            "列表文件为空或格式错误。每行应为: file 'path' 或 file 'http://...'"
        )

    created_temp = temp_dir is None
    if temp_dir is None:
        temp_dir = tempfile.mkdtemp()

    try:
        local_paths = []
        for i, p in enumerate(paths):
            local_paths.append(resolve_path(p, temp_dir))

        clips = []
        for path in local_paths:
            clip = VideoFileClip(path)
            clips.append(clip)

        final = concatenate_videoclips(clips)
        # 不丢帧：不设 fps，保持原时间轴；压缩：降低码率
        final.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            bitrate=bitrate,
            audio_bitrate=audio_bitrate,
            ffmpeg_params=["-movflags", "+faststart"],
        )
        for c in clips:
            c.close()
        final.close()
        return os.path.abspath(output_path)
    finally:
        if created_temp and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="从 mapbinlist.txt 读取列表，合并并压缩为单个 mp4（不丢帧）"
    )
    parser.add_argument(
        "list_file",
        nargs="?",
        default=DEFAULT_LIST_PATH,
        help="列表文件路径（默认: 与脚本同目录的 mapbinlist.txt）",
    )
    parser.add_argument(
        "-o", "--output",
        default="merged.mp4",
        help="输出 mp4 路径（默认 merged.mp4）",
    )
    parser.add_argument(
        "-b", "--bitrate",
        default="800k",
        help="视频码率，越小越糊、体积越小（默认 800k）",
    )
    parser.add_argument(
        "--audio-bitrate",
        default="128k",
        help="音频码率（默认 128k）",
    )
    args = parser.parse_args()

    output_path = args.output
    if output_path == "merged.mp4":
        os.makedirs(TMP_DIR, exist_ok=True)
        output_path = os.path.join(TMP_DIR, "merged.mp4")

    try:
        out = merge_mp4_from_list(
            args.list_file,
            output_path,
            bitrate=args.bitrate,
            audio_bitrate=args.audio_bitrate,
        )
        print("合并完成: {}".format(out))
    except Exception as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
