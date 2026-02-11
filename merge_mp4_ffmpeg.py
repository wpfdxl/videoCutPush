#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通过「列表文件」用 ffmpeg concat 合并 mp4，与命令行等价：
  ffmpeg -f concat -safe 0 -protocol_whitelist "file,http,https,tcp,tls,crypto,data,httpproxy,httpsproxy" -i mapbinlist.txt -c copy merged_output.mp4
不重新编码（-c copy），速度快，无损。
列表文件格式（每行一个）：
  file 'path/to/a.mp4'
  file 'http://cdn.example.com/b.mp4'
"""

import subprocess
import sys
import argparse
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(BASE_DIR, "tmp")


def _read_concat_list(list_path):
    """读取列表文件，每行应为 file 'path' 或 file path，返回有效行列表。"""
    with open(list_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    valid = [ln for ln in lines if ln.startswith("file ")]
    return valid


def merge_by_concat_list(list_path, output_path, ffmpeg_bin="ffmpeg"):
    """
    用 ffmpeg concat 解复用器按列表文件合并，-c copy 不重编码。
    :param list_path: 列表文件路径，内容格式为每行 file '...'
    :param output_path: 输出 mp4 路径
    :param ffmpeg_bin: ffmpeg 可执行文件路径或命令名
    :return: 成功返回输出路径，失败抛异常
    """
    if not os.path.isfile(list_path):
        raise FileNotFoundError("列表文件不存在: {}".format(list_path))

    valid_lines = _read_concat_list(list_path)
    if not valid_lines:
        raise ValueError(
            "列表文件为空或格式错误。每行应为: file 'path/to/video.mp4' 或 file 'http://...'，例如：\n"
            "  file '/path/to/a.mp4'\n"
            "  file 'http://dlcdn1.cgyouxi.com/shareres/xx/xx.mp4'"
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
    ret = subprocess.run(cmd, capture_output=True, text=True)
    if ret.returncode != 0:
        raise RuntimeError("ffmpeg 执行失败:\n{}".format(ret.stderr or ret.stdout))
    return os.path.abspath(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="用 ffmpeg concat + -c copy 按列表文件合并 mp4（不重编码）"
    )
    parser.add_argument(
        "list_file",
        help="列表文件路径，每行格式: file 'path_or_url'，如 mapbinlist.txt",
    )
    parser.add_argument(
        "-o", "--output",
        default="merged_output.mp4",
        help="输出 mp4 路径（默认 merged_output.mp4）",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg 命令或可执行路径（默认 ffmpeg）",
    )
    args = parser.parse_args()

    output_path = args.output
    if output_path == "merged_output.mp4":
        os.makedirs(TMP_DIR, exist_ok=True)
        output_path = os.path.join(TMP_DIR, "merged_output.mp4")
    print("开始合并,开始时间 %s" %(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
    try:
        out = merge_by_concat_list(args.list_file, output_path, args.ffmpeg)
        print("合并完成: {}，结束时间: {}".format(out,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
    except Exception as e:
        print("错误: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
