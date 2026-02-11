#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
python2.7
工程化流程：
- 列表来源：mapbinlist 可为本地文件路径或公网 URL（自动拉取内容）。
- 工作目录：每次运行在 tmp/ 下新建 merge_YYYYMMDD_HHMMSS/，内含下载分片、合并结果。
- 临时文件：分片视频、concat 列表、merged_raw 在合并结束后自动删除，仅保留最终合并视频。

流程：读取 mapbinlist（本地/URL）-> 在 tmp/<run_id>/ 下载分片 -> 生成 concat 列表 ->
ffmpeg concat 合并 -> remux 修复时间戳 -> 删除临时文件，保留合并结果。

列表格式（每行一个）：
  file 'path/to/a.mp4'
  file 'http://cdn.example.com/b.mp4'
"""

import subprocess
import sys
import argparse
import os
import time
import shutil
import hashlib
from multiprocessing.dummy import Pool as ThreadPool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(BASE_DIR, "tmp")
# 与合并结果同层级，存放分片、concat 列表、merged_raw 等临时文件
TMP_SUBDIR_NAME = "_tmp"

# 并发下载数量（保持 mapbinlist 顺序，仅并发执行下载/复制）
DOWNLOAD_CONCURRENCY = 4

try:
    import requests
except ImportError:
    requests = None


def _parse_concat_list_from_content(content):
    """
    从字符串解析列表，每行格式：file 'path' 或 file "path"。
    返回路径/URL 列表（已去掉引号）。
    """
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
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


def _load_mapbinlist(list_source):
    """
    读取 mapbinlist：list_source 可以是本地文件路径或公网 URL。
    返回路径/URL 列表。
    """
    if list_source.startswith("http://") or list_source.startswith("https://"):
        if requests is None:
            raise RuntimeError("从 URL 读取列表需安装 requests: pip install requests")
        r = requests.get(list_source, timeout=30)
        r.raise_for_status()
        content = r.text
    else:
        if not os.path.isfile(list_source):
            raise IOError("列表文件不存在: {}".format(list_source))
        with open(list_source, "r") as f:
            content = f.read()
    return _parse_concat_list_from_content(content)


def _parse_concat_list(list_path):
    """
    读取列表文件，每行格式：file 'path' 或 file "path"。
    返回路径/URL 列表（已去掉引号）。
    """
    with open(list_path, "r") as f:
        content = f.read()
    return _parse_concat_list_from_content(content)


def _default_output_basename(paths):
    """
    根据列表中的路径/URL 顺序生成唯一 MD5，用作默认输出文件名（不含扩展名）。
    同一列表多次运行得到相同文件名，不同列表得到不同文件名。
    """
    raw = "\n".join(paths)
    if not isinstance(raw, type(b"")):
        raw = raw.encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _read_concat_list(list_path):
    """读取列表文件，每行应为 file 'path' 或 file path，返回有效行列表。"""
    with open(list_path, "r") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    valid = [ln for ln in lines if ln.startswith("file ")]
    return valid


def _download_from_url(url, save_path, timeout=120):
    """
    从 URL 下载文件到本地路径（使用 requests，与之前下载方式一致）。
    """
    if requests is None:
        raise RuntimeError("下载 URL 需安装 requests: pip install requests")
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def _basename_from_path(path_or_url):
    """从本地路径或 URL 取文件名（用于 序号_原文件名.mp4）。"""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        part = path_or_url.split("?")[0].rstrip("/")
        return part.split("/")[-1] if part else "video.mp4"
    return os.path.basename(path_or_url) or "video.mp4"


def _fetch_one(item, dest):
    """下载或复制单个文件到 dest（供并发调用）。"""
    if item.startswith("http://") or item.startswith("https://"):
        _download_from_url(item, dest)
    else:
        if not os.path.isfile(item):
            raise IOError("本地文件不存在: {}".format(item))
        shutil.copy2(item, dest)


def _fetch_one_task(args):
    """(item, dest) -> 调用 _fetch_one，供 Pool.map 使用。"""
    item, dest = args
    _fetch_one(item, dest)


def _prepare_videos_to_dir(paths, work_dir):
    """
    将列表中每个路径/URL 并发下载或复制到 work_dir。
    命名为 000_原文件名.mp4, 001_原文件名.mp4, ... 严格按 mapbinlist 顺序。
    返回生成的本地文件名列表（相对 work_dir），顺序与 paths 一致。
    """
    if not os.path.isdir(work_dir):
        os.makedirs(work_dir)
    # 按 mapbinlist 顺序预先生成所有目标路径和本地名
    tasks = []
    local_names = []
    for i, item in enumerate(paths):
        base = _basename_from_path(item)
        if not base.lower().endswith(".mp4"):
            base = base + ".mp4"
        name = "{}_{}".format(i, base)
        dest = os.path.join(work_dir, name)
        tasks.append((item, dest))
        local_names.append(name)
    # 并发执行下载/复制，完成顺序不定，但文件名和 local_names 已按顺序（Python 2.7 用 multiprocessing.dummy）
    workers = min(DOWNLOAD_CONCURRENCY, len(tasks))
    if workers <= 0:
        return local_names
    pool = ThreadPool(workers)
    try:
        pool.map(_fetch_one_task, tasks)
    finally:
        pool.close()
        pool.join()
    return local_names


def _write_local_concat_list(work_dir, local_names, list_filename="concat_list.txt"):
    """
    在 work_dir 下生成 concat 列表文件。
    使用绝对路径写入每个视频路径，避免 ffmpeg 在不同 CWD 下（如服务器与本机）解析相对路径失败。
    行格式：file '/abs/path/merge_mp4_xxx/583_原文件名.mp4'
    返回该列表文件的绝对路径。
    """
    list_path = os.path.join(work_dir, list_filename)
    work_dir_abs = os.path.abspath(work_dir)
    with open(list_path, "w") as f:
        for name in local_names:
            # 绝对路径，不依赖运行脚本时的当前工作目录
            path = os.path.join(work_dir_abs, name)
            escaped = path.replace("'", "'\\''")
            f.write("file '{}'\n".format(escaped))
    return os.path.abspath(list_path)


def merge_by_concat_list(list_path, output_path, ffmpeg_bin="ffmpeg"):
    """
    用 ffmpeg concat 解复用器按列表文件合并，-c copy 不重编码。
    :param list_path: 列表文件路径，内容格式为每行 file '...'
    :param output_path: 输出 mp4 路径
    :param ffmpeg_bin: ffmpeg 可执行文件路径或命令名
    :return: 成功返回输出路径，失败抛异常
    """
    if not os.path.isfile(list_path):
        raise IOError("列表文件不存在: {}".format(list_path))

    valid_lines = _read_concat_list(list_path)
    if not valid_lines:
        raise ValueError(
            "列表文件为空或格式错误。每行应为: file 'path/to/video.mp4' 或 file 'http://...'"
        )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto,data,httpproxy,httpsproxy",
        "-i", os.path.abspath(list_path),
        "-c", "copy",
        os.path.abspath(output_path),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 执行失败:\n{}".format(stderr or stdout))
    return os.path.abspath(output_path)


def fix_timestamps_remux(input_path, output_path, ffmpeg_bin="ffmpeg"):
    """
    对合并后的 mp4 做一次 remux：重新生成 PTS，使时间戳连续。
    使用 -c copy，不重编码，仅重写时间戳。若上传 B 站仍报时间戳跳变，请用 --reencode。
    添加 movflags +faststart 以优化流媒体播放。
    """
    if not os.path.isfile(input_path):
        raise IOError("输入文件不存在: {}".format(input_path))
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", os.path.abspath(input_path),
        "-c", "copy",
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        os.path.abspath(output_path),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 修复时间戳失败:\n{}".format(stderr or stdout))
    return os.path.abspath(output_path)


def _ffmpeg_stderr_text(stderr_bytes):
    """将 FFmpeg 的 stderr 转为可打印字符串（兼容 Python 2 的 bytes）。"""
    if stderr_bytes is None:
        return ""
    if isinstance(stderr_bytes, str):
        return stderr_bytes
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return stderr_bytes.decode(enc)
        except (UnicodeDecodeError, AttributeError):
            continue
    return repr(stderr_bytes)


def _check_reencode_encoders(ffmpeg_bin="ffmpeg"):
    """
    检查当前 FFmpeg 是否支持重编码所需编码器（libx264、aac）。
    若不支持则抛出 RuntimeError，提示用户安装带 libx264 的 FFmpeg。
    """
    proc = subprocess.Popen(
        [ffmpeg_bin, "-encoders"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = proc.communicate()
    text = (out or b"") + (err or b"")
    try:
        dec = text.decode("utf-8") if isinstance(text, bytes) else text
    except Exception:
        dec = text.decode("latin-1") if isinstance(text, bytes) else str(text)
    has_x264 = "libx264" in dec and "libx264" in dec.split("encoders:")[-1]
    has_aac = " aac " in dec or " aac\n" in dec
    if not has_x264:
        raise RuntimeError(
            "当前 FFmpeg 未编译进 libx264，无法进行重编码。\n"
            "请安装带 libx264 的 FFmpeg（如从源码编译时加上 --enable-libx264），\n"
            "或先不使用 --reencode，仅用 remux 修复时间戳。"
        )
    if not has_aac:
        raise RuntimeError(
            "当前 FFmpeg 不支持 AAC 音频编码，无法进行重编码。\n"
            "请安装支持 AAC 的 FFmpeg，或先不使用 --reencode。"
        )


def fix_timestamps_reencode(input_path, output_path, ffmpeg_bin="ffmpeg"):
    """
    对合并后的 mp4 做一次完整重编码（重新压制），生成连续时间轴，供 B 站等严格校验平台使用。
    严格对齐 B 站官方剪辑软件导出参数：1080P / 30fps / 中码率 / mp4 / H.264。

    关键参数说明：
    - vf scale: 强制缩放到 1080P（高度 1080，宽度按比例自动计算且保持偶数）
    - r 30: 强制恒定 30fps 输出，消除可变帧率（VFR）问题
    - vsync cfr: 确保恒定帧率输出
    - profile:v high / level 4.1: B 站推荐的 H.264 配置
    - maxrate / bufsize: 码率上限，防止峰值过高导致 B 站转码失败
    - g 60 / keyint_min 30: 关键帧间隔 2 秒（30fps × 2），B 站友好
    - pix_fmt yuv420p: 最通用的色彩空间
    - ar 48000 / ac 2: 标准音频参数
    - movflags +faststart: moov atom 前置，网页播放友好
    """
    if not os.path.isfile(input_path):
        raise IOError("输入文件不存在: {}".format(input_path))
    _check_reencode_encoders(ffmpeg_bin)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", os.path.abspath(input_path),
        # ---- 视频编码参数（对齐 B 站官方导出：1080P / 30fps / H.264） ----
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-maxrate", "6000k",
        "-bufsize", "12000k",
        "-profile:v", "high",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
        # 强制 30fps 恒定帧率
        "-r", "30",
        "-vsync", "cfr",
        # 关键帧间隔 2 秒（30fps × 2 = 60），B 站转码友好
        "-g", "60",
        "-keyint_min", "30",
        "-bf", "2",
        # 强制缩放到 1080P（宽度自动按比例，保持偶数像素）
        "-vf", "scale=-2:1080",
        # ---- 音频编码参数 ----
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        # ---- 时间戳修复 ----
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        # ---- MP4 优化 ----
        "-movflags", "+faststart",
        os.path.abspath(output_path),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        err_text = _ffmpeg_stderr_text(stderr) or _ffmpeg_stderr_text(stdout)
        raise RuntimeError("ffmpeg 重新压制失败:\n{}".format(err_text))
    return os.path.abspath(output_path)


def _cleanup_temp_dir(temp_dir):
    """
    删除临时文件目录（与合并结果同层级的 _tmp），只保留外层的合成视频。
    """
    if temp_dir and os.path.isdir(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="按 mapbinlist 下载/复制视频到临时目录，合并为单个 mp4，并修复时间戳以兼容三方平台"
    )
    parser.add_argument(
        "list_source",
        help="列表来源：本地文件路径或公网 URL，每行格式: file 'path_or_url'，如 mapbinlist.txt 或 http://example.com/list.txt",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出 mp4 路径（不传则按列表内容 MD5 命名：tmp/<run_id>/<md5>.mp4）",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg 命令或可执行路径（默认 ffmpeg）",
    )
    parser.add_argument(
        "--keep-tmp",
        action="store_true",
        help="合并完成后保留临时分片与中间文件（默认会删除，仅保留合并结果）",
    )
    parser.add_argument(
        "--no-fix-timestamps",
        action="store_true",
        help="不修复时间戳（默认会 remux 一次）",
    )
    parser.add_argument(
        "--reencode",
        action="store_true",
        help="合并后完整重编码（重新压制），时间轴彻底连续，上传 B 站等平台时若仍报时间戳跳变请用此选项",
    )
    # 推送：可选推送到 B 站等平台，形成闭环
    parser.add_argument(
        "--push",
        metavar="PLATFORM",
        default=None,
        help="合并完成后推送到指定平台：bilibili（API 投稿）、playwright_bilibili（Playwright 浏览器投稿，见 playwright_push/）（不传则不推送）",
    )
    parser.add_argument(
        "--push-cookie",
        default=None,
        help="推送平台 Cookie 文件路径（B 站默认 push/bilibili/cookie.json）",
    )
    parser.add_argument(
        "--push-login",
        action="store_true",
        help="推送前进行扫码登录（无 Cookie 或失效时）",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="投稿标题（与 --push 同时使用时必填，≤80 字）",
    )
    parser.add_argument(
        "--desc",
        default="",
        help="投稿简介/描述",
    )
    parser.add_argument(
        "--tid",
        type=int,
        default=21,
        help="B 站分区 id，如 21 日常、160 生活、5 娱乐（默认 21）",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="B 站标签，逗号分隔，如 生活,日常",
    )
    args = parser.parse_args()

    try:
        paths = _load_mapbinlist(args.list_source)
    except (IOError, RuntimeError) as e:
        print("错误: {}".format(e))
        sys.exit(1)

    if not paths:
        print("错误: 列表为空或格式错误，每行应为: file 'path_or_url'")
        sys.exit(1)

    if not os.path.exists(TMP_DIR):
        os.makedirs(TMP_DIR)
    run_id = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    work_dir = os.path.join(TMP_DIR, "merge_{}".format(run_id))
    temp_dir = os.path.join(work_dir, TMP_SUBDIR_NAME)
    os.makedirs(work_dir)
    os.makedirs(temp_dir)

    output_path = args.output
    if output_path is None:
        output_path = os.path.join(work_dir, _default_output_basename(paths) + ".mp4")
    else:
        output_path = os.path.abspath(output_path)

    local_names = []
    try:
        print("开始时间: {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
        print("工作目录: {}（临时文件在 {}）".format(work_dir, TMP_SUBDIR_NAME))
        print("正在下载/复制 {} 个视频到临时目录...".format(len(paths)))
        local_names = _prepare_videos_to_dir(paths, temp_dir)
        print("下载完成时间: {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
        print("已就绪，生成临时 concat 列表...")
        list_path = _write_local_concat_list(temp_dir, local_names)
        print("开始合并...")
        merged_raw = os.path.join(temp_dir, "merged_raw.mp4")
        merge_by_concat_list(list_path, merged_raw, args.ffmpeg)
        if args.reencode:
            print("合并完成，正在重新压制（重编码）以兼容 B 站等平台...")
            out = fix_timestamps_reencode(merged_raw, output_path, args.ffmpeg)
            print("合并并重新压制完成: {}，结束时间: {}".format(
                out, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            ))
        else:
            print("合并完成，正在修复时间戳（remux）以兼容三方平台...")
            out = fix_timestamps_remux(merged_raw, output_path, args.ffmpeg)
            print("合并并修复完成: {}，结束时间: {}".format(
                out, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            ))

        # 可选：推送到 B 站等平台
        if args.push:
            if args.push == "playwright_bilibili":
                # 合并后 import 包 playwright_push.upload_bilibili 的 main 上传（Playwright 浏览器投稿）
                playwright_push_dir = os.path.join(BASE_DIR, "playwright_push")
                if not os.path.isdir(playwright_push_dir):
                    print("错误: 未找到 playwright_push 目录")
                    sys.exit(1)
                try:
                    if BASE_DIR not in sys.path:
                        sys.path.insert(0, BASE_DIR)
                    from playwright_push.upload_bilibili import main as playwright_upload_main
                    print("正在通过 Playwright 推送到 B 站（playwright_bilibili）...")
                    res = playwright_upload_main(
                        video_path_arg=os.path.abspath(out),
                        title_arg=args.title.strip() if args.title else None,
                    )
                    print("Playwright 投稿流程已结束: 文件={}, 审核状态={}, 原因={}, 成功={}".format(
                        res.filename, res.audit_status, res.reason, res.success
                    ))
                    if not res.success:
                        sys.exit(1)
                except SystemExit:
                    raise
                except Exception as e:
                    print("Playwright 推送失败: {}".format(e))
                    sys.exit(1)
            else:
                try:
                    if BASE_DIR not in sys.path:
                        sys.path.insert(0, BASE_DIR)
                    from push import get_pusher
                    cookie_path = args.push_cookie
                    if args.push == "bilibili" and not cookie_path:
                        cookie_path = os.path.join(BASE_DIR, "push", "bilibili", "cookie.json")
                    pusher = get_pusher(args.push, cookie_path=cookie_path)
                    if args.push_login:
                        if not pusher.login(use_qrcode=True, save_cookie_path=cookie_path):
                            print("错误: 扫码登录失败")
                            sys.exit(1)
                    if not pusher.is_logged_in():
                        print("错误: 未登录或 Cookie 已失效，请提供有效 Cookie 或使用 --push-login 扫码登录")
                        sys.exit(1)
                    print("正在推送到 {}...".format(args.push))
                    result = pusher.upload(
                        out,
                        title=args.title.strip(),
                        desc=args.desc or "",
                        tid=args.tid,
                        tag=args.tag.strip().split(",") if args.tag else None,
                    )
                    print("投稿成功: {}".format(result.get("data", result)))
                except Exception as e:
                    print("推送失败: {}".format(e))
                    sys.exit(1)
    except Exception as e:
        print("错误: {}".format(e))
        sys.exit(1)
    finally:
        # 合并完成后删除临时目录（仅保留最终视频）；传 --keep-tmp 则保留
        if not args.keep_tmp:
            _cleanup_temp_dir(temp_dir)


if __name__ == "__main__":
    main()
