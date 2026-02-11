#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 mapbinlist.txt 读取视频列表，逐个调用 playwright_push 的 B 站上传并发布。
支持本地文件路径和 http(s) URL（URL 会先下载到临时目录再上传）。
"""
from __future__ import print_function

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPBINLIST = os.path.join(BASE_DIR, "mapbinlist.txt")
TMP_VIDEOS_DIR = os.path.join(BASE_DIR, "tmp", "playwright_push_videos")


def _parse_mapbinlist(path):
    """解析 mapbinlist 文件，每行 file 'path' 或 file \"path\"，返回路径/URL 列表。"""
    with open(path, "r") as f:
        content = f.read()
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


def _download_url(url, save_path, timeout=300):
    """下载 URL 到本地文件。"""
    try:
        import requests
    except ImportError:
        raise RuntimeError("下载 URL 需安装 requests: pip install requests")
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def _ensure_local_path(entry):
    """
    若 entry 为本地路径且文件存在则返回绝对路径；
    若为 http(s) URL 则下载到 TMP_VIDEOS_DIR 并返回本地路径。
    否则返回 None。
    """
    if not entry:
        return None
    if entry.startswith("http://") or entry.startswith("https://"):
        if not os.path.isdir(TMP_VIDEOS_DIR):
            os.makedirs(TMP_VIDEOS_DIR)
        # 用 URL 最后一段或简单命名
        name = os.path.basename(entry.split("?")[0]) or "video.mp4"
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        save_path = os.path.join(TMP_VIDEOS_DIR, name)
        if not os.path.isfile(save_path):
            print("正在下载: {} -> {}".format(entry[:60], save_path))
            _download_url(entry, save_path)
        return os.path.abspath(save_path)
    # 本地路径
    path = os.path.abspath(entry)
    if os.path.isfile(path):
        return path
    return None


def main():
    if not os.path.isfile(MAPBINLIST):
        print("错误: 未找到 mapbinlist.txt: {}".format(MAPBINLIST))
        sys.exit(1)

    paths = _parse_mapbinlist(MAPBINLIST)
    if not paths:
        print("错误: mapbinlist.txt 中没有有效视频条目（每行格式: file 'path_or_url'）")
        sys.exit(1)

    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from playwright_push.upload_bilibili import main as upload_main

    results = []
    for i, entry in enumerate(paths):
        print("\n[{}/{}] 处理: {}".format(i + 1, len(paths), entry[:80]))
        local_path = _ensure_local_path(entry)
        if not local_path:
            print("  跳过: 非本地文件或下载失败")
            results.append((entry, None))
            continue
        title = os.path.splitext(os.path.basename(local_path))[0]
        res = upload_main(video_path_arg=local_path, title_arg=title)
        results.append((entry, res))
        print("  结果: 文件={}, 审核状态={}, 原因={}, 成功={}".format(
            res.filename, res.audit_status, res.reason, res.success
        ))

    # 汇总
    success_count = sum(1 for _, r in results if r and r.success)
    print("\n======== 汇总 ========")
    print("共 {} 个视频，成功 {} 个".format(len(results), success_count))
    for entry, res in results:
        if res:
            print("  {} -> {} ({}): {}".format(
                os.path.basename(entry.split("?")[0]) or entry[:40],
                res.audit_status,
                res.success,
                res.reason[:50] if res.reason else "",
            ))
        else:
            print("  {} -> 跳过".format(entry[:60]))

    if success_count < len([r for _, r in results if r is not None]):
        sys.exit(1)


if __name__ == "__main__":
    main()
