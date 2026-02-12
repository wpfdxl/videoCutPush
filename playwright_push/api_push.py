# -*- coding: utf-8 -*-
"""
Playwright B 站投稿 POST 接口：接收 mp4 地址数组，先按 merge_mp4_ffmpeg2 逻辑合并成一个视频，
再推送到 B 站。返回 code + data（审核状态、DedeUserID、视频名称、错误原因、耗时）。
启动：python3 -m playwright_push.api_push  或  flask --app playwright_push.api_push run
"""
from __future__ import print_function

import os
import shutil
import sys
import time

# 确保项目根在 path 中
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from flask import Flask, request, jsonify

app = Flask(__name__)


def _api_log(msg):
    """接口层日志：带时间戳。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print("{} [api] {}".format(ts, msg))


# 接口使用的 cookie 文件：与 api_push 同目录的 cookie.json（绝对路径，避免 cwd 影响）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COOKIE_FILE = os.path.abspath(os.path.join(_SCRIPT_DIR, "cookie.json"))


def _run_upload(video_path, title, gindex, guid, version=None):
    from playwright_push.upload_bilibili import main as playwright_upload_main
    return playwright_upload_main(
        video_path_arg=os.path.abspath(video_path),
        title_arg=title,
        gindex=gindex,
        guid=guid,
        version=version,
        cookie_file=_COOKIE_FILE,
    )


@app.route("/push/playwright_bilibili", methods=["POST"])
def push_playwright_bilibili():
    """
    先按 merge_mp4_ffmpeg2 逻辑将 videos 数组合并成一个 mp4，再推送该视频到 B 站。
    POST 请求体 JSON:
      videos: mp4 路径或 URL 数组，顺序即合成顺序
      gindex, guid, version: 可选，日志与返回会原样带上
      retry: 可选，推送失败重试次数，默认 1
      reencode: 可选，是否合并后重编码（默认 false）
      title: 可选，投稿标题
    响应 JSON:
      code: 0 仅当审核状态为「已通过」(passed) 或「未通过」(rejected)，由 data[0].audit_status 区分
      code: -100 视频合并前/合并报错（参数错误或合并失败）
      code: -200 其余失败：Cookie 错误、push 失败、超时、未提交成功等，失败原因在 data[0].error_reason
      data: 数组一项，含 audit_status, DedeUserID, video_name, error_reason, duration_sec, gindex, guid, version
    """
    request_start = time.time()
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        _api_log("接口请求失败 code=-100: 无效 JSON")
        return jsonify({"code": -100, "data": None, "msg": "无效 JSON"}), 200

    videos = body.get("videos")
    if not videos or not isinstance(videos, list):
        _api_log("接口请求失败 code=-100: 缺少参数 videos")
        return jsonify({"code": -100, "data": None, "msg": "缺少参数 videos（mp4 路径或 URL 数组）"}), 200

    paths = []
    for v in videos:
        p = (v if isinstance(v, str) else str(v)).strip()
        if p:
            paths.append(p)

    if not paths:
        _api_log("接口请求失败 code=-100: videos 为空")
        return jsonify({"code": -100, "data": None, "msg": "videos 不能为空"}), 200

    gindex = body.get("gindex")
    guid = body.get("guid", "")
    version = body.get("version", "")
    retry = int(body.get("retry", 1))
    if retry < 0:
        retry = 1
    reencode = bool(body.get("reencode", False))
    title = body.get("title") or ""

    _api_log("接口请求 gindex={} guid={} version={} videos_count={} reencode={} retry={}".format(
        gindex, guid, version, len(paths), reencode, retry
    ))

    # 1) 按 merge_mp4_ffmpeg2 逻辑合并为一个视频
    merge_start = time.time()
    try:
        from merge_mp4_ffmpeg2 import merge_paths_to_one
        merged_path = merge_paths_to_one(
            paths,
            output_path=None,
            base_dir=_BASE,
            reencode=reencode,
            ffmpeg_bin="ffmpeg",
            keep_tmp=False,
        )
    except Exception as e:
        _api_log("视频合成失败 code=-100，耗时 {:.2f} 秒: {}".format(time.time() - merge_start, e))
        return jsonify({
            "code": -100,
            "data": None,
            "msg": "合并失败: {}".format(e),
        }), 200

    merge_elapsed = round(time.time() - merge_start, 2)
    _api_log("视频合成完成，耗时 {} 秒，输出: {}".format(merge_elapsed, merged_path))
    _api_log("使用 Cookie 文件: {} (存在: {})".format(_COOKIE_FILE, os.path.isfile(_COOKIE_FILE)))

    video_name = os.path.basename(merged_path)
    if not title:
        title = os.path.splitext(video_name)[0]

    # 2) 推送合并后的视频到 B 站（带重试）
    last_result = None
    last_error = None
    max_attempts = max(1, retry + 1)
    for attempt in range(max_attempts):
        try:
            res = _run_upload(merged_path, title, gindex, guid, version)
            last_result = res
            last_error = None
            if res.success:
                break
        except Exception as e:
            last_error = e
            last_result = None
            if attempt + 1 < max_attempts:
                continue

    # 仅当审核状态为「已通过」或「未通过」时 code=0；其余（Cookie 错误、push 失败、超时等）均为 code=-200
    def _make_data_item(result, video_name_override=None):
        return {
            "audit_status": result.audit_status if result else "error",
            "DedeUserID": (result.dede_user_id or "") if result else "",
            "video_name": (result.filename if result else video_name_override) or video_name,
            "error_reason": (result.reason or "") if result else (str(last_error) if last_error else ""),
            "duration_sec": (result.duration_sec or 0) if result else 0,
            "gindex": gindex,
            "guid": guid or "",
            "version": version or "",
        }

    def _remove_merged_file():
        if not merged_path:
            return
        try:
            if os.path.isfile(merged_path):
                os.remove(merged_path)
                _api_log("已删除合成临时文件: {}".format(merged_path))
            merge_dir = os.path.dirname(merged_path)
            if merge_dir and os.path.isdir(merge_dir) and "merge_api_" in os.path.basename(merge_dir):
                shutil.rmtree(merge_dir, ignore_errors=True)
                _api_log("已删除合成临时目录: {}".format(merge_dir))
        except Exception as e:
            _api_log("删除合成文件或目录失败: {}".format(e))

    total_elapsed = round(time.time() - request_start, 2)
    if last_result is not None and last_result.audit_status in ("passed", "rejected"):
        # 审核已通过 或 未通过：code=0，由调用方根据 audit_status 判断
        data_item = _make_data_item(last_result)
        data_item["error_reason"] = "" if last_result.audit_status == "passed" else (last_result.reason or "")
        _api_log("接口请求完成 code=0，审核状态={}，总耗时 {} 秒".format(last_result.audit_status, total_elapsed))
        _remove_merged_file()
        return jsonify({"code": 0, "data": [data_item]})

    # 其余均为 code=-200：Cookie 错误、push 失败、超时、未提交成功等
    data_item = _make_data_item(last_result, video_name_override=video_name)
    _api_log("接口请求完成 code=-200，原因: {}，总耗时 {} 秒".format(
        (last_result.reason if last_result else (str(last_error) if last_error else "")) or "失败", total_elapsed
    ))
    _remove_merged_file()
    return jsonify({"code": -200, "data": [data_item]}), 200


if __name__ == "__main__":
    COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.json")
    print("cookie_file: {}".format(COOKIE_FILE))

    import argparse
    ap = argparse.ArgumentParser(description="Playwright B 站投稿 POST 接口")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址")
    ap.add_argument("--port", type=int, default=8188, help="端口")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port)
