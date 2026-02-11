#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通过 cv2 (OpenCV) 按 mapbinlist.txt 列表高效合并视频，并保留音频。
- 列表格式与 ffmpeg concat 一致：每行 file 'path' 或 file 'url'
- 支持本地路径与 http(s) URL（URL 会先下载到临时目录）
- 不丢帧，按首段分辨率与 fps 统一输出；分辨率不一致时自动缩放
- 画质适度压缩（H.264/mp4v），音频由 ffmpeg 按顺序拼接后混流到最终文件
"""

import os
import sys
import time
import tempfile
import argparse
import shutil
import subprocess

try:
    import cv2
except ImportError:
    print("请先安装依赖: pip install opencv-python")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None

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
        if (rest.startswith("'") and rest.endswith("'")) or (
            rest.startswith('"') and rest.endswith('"')
        ):
            rest = rest[1:-1]
        if rest:
            paths.append(rest)
    return paths

def download_from_url(url, save_path, timeout=120, verify_ssl=True, max_retries=3):
    """
    从 URL 下载文件到本地路径。
    遇 SSL 不稳定（如 SSLEOFError）时自动重试；仍失败时可配合 --no-verify-ssl 使用。
    """
    if requests is None:
        raise RuntimeError("支持 URL 需安装 requests: pip install requests")
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(
                url, stream=True, timeout=timeout, verify=verify_ssl
            )
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(1 + attempt)
            else:
                if verify_ssl:
                    raise RuntimeError(
                        "下载失败(SSL/连接): {}。可尝试加参数: --no-verify-ssl（仅用于可信源）".format(e)
                    )
                raise
    if last_err is not None:
        raise last_err


def resolve_path(item, temp_dir, verify_ssl=True):
    """若为 URL 则下载到 temp_dir 并返回本地路径，否则校验本地文件存在后返回。"""
    if item.startswith("http://") or item.startswith("https://"):
        name = os.path.basename(item.split("?")[0]) or "video_{}.mp4".format(
            abs(hash(item)) % 100000
        )
        local_path = os.path.join(temp_dir, name)
        download_from_url(item, local_path, verify_ssl=verify_ssl)
        return local_path
    if not os.path.isfile(item):
        raise FileNotFoundError("本地文件不存在: {}".format(item))
    return item


def get_video_props(cap):
    """从 VideoCapture 获取 width, height, fps。"""
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or fps > 240:
        fps = 25.0
    return w, h, fps


def _fourcc_lossless():
    """无损编码 FFV1 的 fourcc。"""
    return cv2.VideoWriter_fourcc("F", "F", "V", "1")


def _fourcc_mp4():
    """常用 mp4 编码，优先 H.264 类。"""
    for codec in ("avc1", "H264", "X264", "mp4v"):
        fourcc = cv2.VideoWriter_fourcc(*codec)
        # 简单校验：有的环境 fourcc 返回 -1 表示不支持
        if fourcc != -1:
            return fourcc
    return cv2.VideoWriter_fourcc(*"mp4v")


def _mux_audio_with_ffmpeg(video_only_path, local_paths, output_path, audio_bitrate="128k", ffmpeg_bin="ffmpeg"):
    """
    用 ffmpeg 按 local_paths 顺序拼接各段音频，再与无音轨视频混流为最终 mp4。
    :param video_only_path: cv2 输出的仅视频文件
    :param local_paths: 各段源视频路径（与 cv2 合并顺序一致）
    :param output_path: 最终带音轨的输出路径
    :param audio_bitrate: 音频码率
    :param ffmpeg_bin: ffmpeg 命令
    :return: 成功返回 output_path，无音轨或失败时返回 None
    """
    temp_dir = os.path.dirname(video_only_path)
    audio_list_path = os.path.join(temp_dir, "audio_concat_list.txt")
    audio_m4a_path = os.path.join(temp_dir, "audio_concat.m4a")

    with open(audio_list_path, "w", encoding="utf-8") as f:
        for p in local_paths:
            # ffmpeg concat 要求路径转义单引号
            escaped = p.replace("'", "'\\''")
            f.write("file '{}'\n".format(escaped))

    # 从各段按顺序只取音频并 concat 成一条 aac
    cmd_audio = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", audio_list_path,
        "-vn", "-c:a", "aac", "-b:a", audio_bitrate,
        audio_m4a_path,
    ]
    ret = subprocess.run(cmd_audio, capture_output=True, text=True)
    if ret.returncode != 0:
        return None

    # 视频 + 音频 混流，-shortest 以较短者为准避免不同步
    cmd_mux = [
        ffmpeg_bin, "-y",
        "-i", video_only_path,
        "-i", audio_m4a_path,
        "-c:v", "copy", "-c:a", "copy",
        "-shortest",
        output_path,
    ]
    ret = subprocess.run(cmd_mux, capture_output=True, text=True)
    if ret.returncode != 0:
        return None
    return output_path


def merge_mp4_cv2(
    list_path,
    output_path,
    lossless=False,
    temp_dir=None,
    verify_ssl=True,
    add_audio=True,
    audio_bitrate="128k",
    ffmpeg_bin="ffmpeg",
):
    """
    使用 cv2 按列表顺序合并视频，不丢帧；可选无损或压缩编码；可选用 ffmpeg 混入音频。
    :param list_path: 列表文件路径（每行 file 'path_or_url'）
    :param output_path: 输出 mp4 路径
    :param lossless: True 使用 FFV1 无损，False 使用 H.264/mp4v 适度压缩
    :param temp_dir: 下载远程文件用的临时目录，不传则自动创建并清理
    :param verify_ssl: 下载 https 时是否校验 SSL 证书
    :param add_audio: 是否用 ffmpeg 按顺序拼接各段音频并混流到最终文件
    :param audio_bitrate: 混流时音频码率
    :param ffmpeg_bin: ffmpeg 命令
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
        for p in paths:
            local_paths.append(resolve_path(p, temp_dir, verify_ssl=verify_ssl))

        # 用第一个视频确定输出尺寸和 fps
        cap0 = cv2.VideoCapture(local_paths[0])
        if not cap0.isOpened():
            raise RuntimeError("无法打开视频: {}".format(local_paths[0]))
        out_w, out_h, out_fps = get_video_props(cap0)
        cap0.release()

        fourcc = _fourcc_lossless() if lossless else _fourcc_mp4()
        ext = os.path.splitext(output_path)[1].lower()
        if ext not in (".mp4", ".avi", ".mkv"):
            output_path = os.path.splitext(output_path)[0] + ".mp4"
        if lossless and not output_path.lower().endswith(".avi"):
            output_path = os.path.splitext(output_path)[0] + "_lossless.avi"

        # 需要混音时先写到临时视频，再与音频混流；否则直接写最终路径
        if add_audio and not lossless:
            video_only_path = os.path.join(temp_dir, "video_only.mp4")
            write_path = video_only_path
        else:
            write_path = output_path

        writer = cv2.VideoWriter(
            write_path, fourcc, out_fps, (out_w, out_h)
        )
        if not writer.isOpened():
            raise RuntimeError(
                "无法创建输出文件（可能不支持所选编码）: {}".format(write_path)
            )

        for path in local_paths:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                writer.release()
                raise RuntimeError("无法打开视频: {}".format(path))
            w, h, _ = get_video_props(cap)
            need_resize = w != out_w or h != out_h
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if need_resize:
                    frame = cv2.resize(
                        frame, (out_w, out_h), interpolation=cv2.INTER_LINEAR
                    )
                writer.write(frame)
            cap.release()

        writer.release()

        if add_audio and not lossless and write_path != output_path:
            muxed = _mux_audio_with_ffmpeg(
                write_path, local_paths, output_path,
                audio_bitrate=audio_bitrate, ffmpeg_bin=ffmpeg_bin
            )
            if muxed:
                return os.path.abspath(muxed)
            # 混音失败（如某段无音轨）则用仅视频作为输出
            shutil.copy2(write_path, output_path)
            if sys.stderr:
                print("警告: 未混入音频（可能某段无音轨或 ffmpeg 失败），已输出仅视频: {}".format(output_path), file=sys.stderr)

        return os.path.abspath(output_path)
    finally:
        if created_temp and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="用 cv2 按 mapbinlist.txt 合并视频（不丢帧、适度压缩画质，默认带音频）"
    )
    parser.add_argument(
        "list_file",
        nargs="?",
        default=DEFAULT_LIST_PATH,
        help="列表文件路径（默认: 同目录 mapbinlist.txt）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="merged_cv2.mp4",
        help="输出视频路径（默认 merged_cv2.mp4，无损时为 .avi）",
    )
    parser.add_argument(
        "--lossless",
        action="store_true",
        help="使用 FFV1 无损编码（体积大，输出为 .avi）",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="下载 https 时跳过 SSL 证书校验（仅用于可信源，如遇 SSLEOFError 可试）",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="不混入音频，仅输出视频（默认会按顺序拼接各段音频）",
    )
    parser.add_argument(
        "--audio-bitrate",
        default="128k",
        help="混流时音频码率（默认 128k）",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg 命令路径（混音时使用，默认 ffmpeg）",
    )
    args = parser.parse_args()

    verify_ssl = not args.no_verify_ssl
    if os.environ.get("INSECURE_SSL") in ("1", "true", "yes"):
        verify_ssl = False

    output_path = args.output
    if output_path == "merged_cv2.mp4":
        os.makedirs(TMP_DIR, exist_ok=True)
        output_path = os.path.join(TMP_DIR, "merged_cv2.mp4")

    try:
        out = merge_mp4_cv2(
            args.list_file,
            output_path,
            lossless=args.lossless,
            verify_ssl=verify_ssl,
            add_audio=not args.no_audio,
            audio_bitrate=args.audio_bitrate,
            ffmpeg_bin=args.ffmpeg,
        )
        print("合并完成: {}".format(out))
    except Exception as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
