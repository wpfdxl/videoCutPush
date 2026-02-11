# -*- coding: utf-8 -*-
"""
B 站投稿上传：preupload -> 分片上传 -> 提交稿件信息。
参考 biliload 与  的投稿流程。
"""
from __future__ import absolute_import

import hashlib
import math
import os
import time
from urllib import parse

try:
    import requests
except ImportError:
    requests = None

# 投稿接口
PREUPLOAD_URL = "https://member.bilibili.com/preupload"
ADD_URL = "https://member.bilibili.com/x/vu/web/add/v3"
APP_ADD_URL = "https://member.bilibili.com/x/vu/app/add"
APP_KEY_BILITV = "4409e2ce8ffd12b8"
APPSEC_BILITV = "59b43e04ad6965f34319062b478f83dd"
UPOS_PROFILE = "ugcupos/bup"
PREUPLOAD_VERSION = "2.14.0"
PREUPLOAD_BUILD = 2140000
# 与  一致：probe_version 用当前  的 20250923，多线路回退
PREUPLOAD_LINES = [
    "probe_version=20250923&upcdn=bldsa&zone=cs",
    "zone=cs&upcdn=bldsa&probe_version=20250923",
    "probe_version=20250923&upcdn=bda2&zone=cs",
    "zone=cs&upcdn=bda2&probe_version=20250923",
]


def _ensure_requests():
    if requests is None:
        raise RuntimeError("上传需要 requests，请执行: pip install requests")


def _sign_app_query(params_str, appsec):
    """APP 接口签名：MD5(params_str + appsec)，小写 hex。与  Credential::sign 一致。"""
    return hashlib.md5((params_str + appsec).encode("utf-8")).hexdigest()


def preupload(session, filepath, upos_profile=None):
    """
    获取上传凭证与分片参数。协议与  对齐（profile ugcupos/bup + version/build）。
    :return: dict 含 endpoint, upos_uri, auth, biz_id, chunk_size 等；失败抛异常
    """
    _ensure_requests()
    if upos_profile is None:
        upos_profile = UPOS_PROFILE
    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    params = {
        "os": "upos",
        "name": filename,
        "size": filesize,
        "r": "upos",
        "profile": upos_profile,
        "ssl": 0,
        "version": PREUPLOAD_VERSION,
        "build": PREUPLOAD_BUILD,
    }
    last_err = None
    for line in PREUPLOAD_LINES:
        try:
            url = "{}?{}".format(PREUPLOAD_URL, line)
            print("[DEBUG] preupload 尝试线路: {}".format(line))
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            j = r.json()
            if j.get("OK") in (1, True):
                print("[DEBUG] preupload 成功，endpoint={}, biz_id={}".format(
                    j.get("endpoint"), j.get("biz_id") or j.get("bizId")
                ))
                return j
            last_err = j
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError("preupload 失败（已尝试多线路）: {}".format(last_err))


def init_multipart(session, endpoint, upos_uri, auth):
    """初始化分片上传，返回 upload_id。"""
    _ensure_requests()
    session.headers["X-Upos-Auth"] = auth
    path = upos_uri.replace("upos://", "")
    url = "https:{}/{}?uploads&output=json".format(endpoint, path)
    r = session.post(url, timeout=30)
    r.raise_for_status()
    j = r.json()
    if not j.get("OK") and j.get("OK") != 1:
        raise RuntimeError("init multipart 失败: {}".format(j))
    return j.get("upload_id")


def _get_etag_from_response(r):
    """从 PUT 响应中解析 ETag（响应头或 JSON body），去掉首尾引号。"""
    etag = r.headers.get("ETag") or r.headers.get("etag")
    if etag:
        return etag.strip('"')
    try:
        j = r.json()
        if isinstance(j, dict):
            etag = j.get("etag") or j.get("ETag")
            if etag:
                return str(etag).strip('"')
    except Exception:
        pass
    return None


def upload_chunks(session, endpoint, upos_uri, upload_id, filepath, chunk_size, biz_id, filename, max_retry=5):
    """
    分片上传文件，并完成 multipart。
    :param session: 带 Cookie 的 requests.Session
    :return: complete 接口返回的 dict，用于提交稿件时确定 filename；失败抛异常
    """
    _ensure_requests()
    path = upos_uri.replace("upos://", "")
    filesize = os.path.getsize(filepath)
    chunks_num = int(math.ceil(filesize / float(chunk_size)))
    etags = []

    with open(filepath, "rb") as f:
        for chunk_index in range(chunks_num):
            chunk_data = f.read(chunk_size)
            if not chunk_data:
                break
            start = chunk_index * chunk_size
            end = start + len(chunk_data)
            part_number = chunk_index + 1

            for attempt in range(max_retry):
                url = (
                    "https:{endpoint}/{path}?"
                    "partNumber={part_number}&uploadId={upload_id}&chunk={chunk}&chunks={chunks}&"
                    "size={size}&start={start}&end={end}&total={total}"
                ).format(
                    endpoint=endpoint,
                    path=path,
                    part_number=part_number,
                    upload_id=upload_id,
                    chunk=chunk_index,
                    chunks=chunks_num,
                    size=len(chunk_data),
                    start=start,
                    end=end,
                    total=filesize,
                )
                r = session.put(url, data=chunk_data, timeout=900)
                if r.status_code == 200:
                    etag = _get_etag_from_response(r)
                    etags.append(etag if etag else "etag")
                    break
                if attempt < max_retry - 1:
                    time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError("分片 {}/{} 上传失败，已达最大重试".format(chunk_index + 1, chunks_num))

    # 完成 multipart（profile 与  一致：ugcupos/bup）
    complete_url = (
        "https:{endpoint}/{path}?name={name}&uploadId={upload_id}&biz_id={biz_id}&output=json&profile=ugcupos%2Fbup"
    ).format(
        endpoint=endpoint,
        path=path,
        name=parse.quote_plus(filename),
        upload_id=upload_id,
        biz_id=biz_id,
    )
    parts_body = {
        "parts": [
            {"partNumber": i, "eTag": etags[i - 1] if i - 1 < len(etags) else "etag"}
            for i in range(1, chunks_num + 1)
        ]
    }
    r = session.post(complete_url, json=parts_body, timeout=60)
    r.raise_for_status()
    j = r.json()
    print("[DEBUG] complete 响应: {}".format(j))
    if not j.get("OK") and j.get("OK") != 1:
        raise RuntimeError("完成分片失败: {}".format(j))
    return j


def submit_add(session, csrf, videos, title, tid, tag, desc, source="", cover="", no_reprint=True, dynamic="", dtime=None):
    """
    提交稿件信息。videos 为 preupload 后得到的列表，每项含 filename(不含扩展名)、title、desc。
    :return: 接口返回的 json（含 aid 等）
    """
    _ensure_requests()
    copyright_type = 2 if source else 1
    payload = {
        "copyright": copyright_type,
        "source": source,
        "title": title,
        "tid": tid,
        "tag": tag if isinstance(tag, str) else ",".join(tag),
        "no_reprint": 1 if no_reprint else 0,
        "desc": desc,
        "cover": cover,
        "mission_id": 0,
        "order_id": 0,
        "videos": videos,
        "open_elec": 1,
        "dynamic": dynamic,
        "subtitle": {"lan": "", "open": 1},
    }
    if dtime is not None:
        payload["dtime"] = dtime
    # 与  submit_by_web 一致：v3 接口且带 t（毫秒时间戳）、csrf
    t_ms = int(time.time() * 1000)
    url = "{}?t={}&csrf={}".format(ADD_URL, t_ms, csrf)
    print("[DEBUG] Web投稿 URL: {}".format(ADD_URL))
    print("[DEBUG] Web投稿 videos: {}".format(videos))
    # complete 后稍等再投稿，避免服务端未处理完导致 21015
    time.sleep(2)
    r = session.post(url, json=payload, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        if j.get("code") == 21015:
            time.sleep(5)
            r2 = session.post(url, json=payload, timeout=30)
            r2.raise_for_status()
            j = r2.json()
            if j.get("code") == 0:
                return j
        msg = "投稿提交失败: {}".format(j)
        if j.get("code") == 21015:
            msg += "（若为合并视频，可尝试合并时加 --reencode 重新压制后再上传）"
        raise RuntimeError(msg)
    return j


def submit_add_by_app(
    session,
    access_token,
    videos,
    title,
    tid,
    tag,
    desc,
    source="",
    cover="",
    no_reprint=True,
    dynamic="",
    dtime=None,
):
    """
    APP 接口投稿（与  submit_by_app 一致），需 access_token（ 登录后 token_info.access_token）。
    :return: 接口返回的 json（含 aid、bvid 等）
    """
    _ensure_requests()
    copyright_type = 2 if source else 1
    payload = {
        "copyright": copyright_type,
        "source": source,
        "title": title,
        "tid": tid,
        "tag": tag if isinstance(tag, str) else ",".join(tag),
        "no_reprint": 1 if no_reprint else 0,
        "desc": desc,
        "cover": cover,
        "mission_id": 0,
        "order_id": 0,
        "videos": videos,
        "open_elec": 1,
        "dynamic": dynamic,
        "subtitle": {"lan": "", "open": 1},
    }
    if dtime is not None:
        payload["dtime"] = dtime

    ts = int(time.time())
    query_params = [
        ("access_key", access_token),
        ("appkey", APP_KEY_BILITV),
        ("build", 7800300),
        ("c_locale", "zh-Hans_CN"),
        ("channel", "bili"),
        ("disable_rcmd", 0),
        ("mobi_app", "android"),
        ("platform", "android"),
        ("s_locale", "zh-Hans_CN"),
        ("statistics", '"appId":1,"platform":3,"version":"7.80.0","abtest":""'),
        ("ts", ts),
    ]
    params_str = parse.urlencode(query_params)
    sign = _sign_app_query(params_str, APPSEC_BILITV)
    url = "{}?{}&sign={}".format(APP_ADD_URL, params_str, sign)
    print("[DEBUG] APP投稿 URL: {}".format(APP_ADD_URL))
    print("[DEBUG] APP投稿 videos: {}".format(videos))
    time.sleep(2)
    r = session.post(
        url,
        json=payload,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 BiliDroid/7.80.0 (bbcallen@gmail.com) os/android model/MI 6 mobi_app/android build/7800300 channel/bili innerVer/7800310 osVer/13 network/2",
        },
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        msg = "APP投稿提交失败: {}".format(j)
        # 检测 token 失效的常见错误码
        if j.get("code") in [-101, -111, -400, -403]:
            msg = "access_token 已失效，请重新登录：\n"
            msg += "  方法1: 删除 push/bilibili/cookie.json 后，运行 --push-login 扫码重新登录\n"
            msg += "  方法2: 使用  login 扫码后，复制其生成的 cookies.json 到 push/bilibili/cookie.json"
            raise RuntimeError(msg)
        if j.get("code") == 21015:
            time.sleep(5)
            app_headers = {
                "User-Agent": "Mozilla/5.0 BiliDroid/7.80.0 (bbcallen@gmail.com) os/android model/MI 6 mobi_app/android build/7800300 channel/bili innerVer/7800310 osVer/13 network/2",
            }
            r2 = session.post(url, json=payload, timeout=30, headers=app_headers)
            r2.raise_for_status()
            j2 = r2.json()
            if j2.get("code") == 0:
                return j2
            msg += "（若为合并视频，可尝试合并时加 --reencode 重新压制后再上传）"
        raise RuntimeError(msg)
    return j
