# -*- coding: utf-8 -*-
"""
B 站推送客户端：组合登录与上传，实现 PusherBase。
"""
from __future__ import absolute_import

import os
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from ..base import PusherBase
from . import auth
from . import upload


# 默认 Cookie 路径（与  习惯一致可用 cookie.json）
DEFAULT_COOKIE_PATH = "cookie.json"


class BilibiliPusher(PusherBase):
    """
    B 站投稿推送。支持 Cookie 文件登录、扫码登录；上传单 P 视频并提交稿件。
    """

    def __init__(self, cookie_path=None, cookie_dict=None, session=None):
        """
        :param cookie_path: Cookie 文件路径（JSON 或 Netscape 格式），默认当前目录 cookie.json
        :param cookie_dict: 直接传入 Cookie 字典，若提供则优先于 cookie_path
        :param session: 可传入已有 requests.Session，否则新建
        """
        self._session = session or (requests.Session() if requests else None)
        # B 站请求直连，不走环境变量代理，避免 ProxyError（代理断开等）
        if self._session is not None:
            self._session.trust_env = False
            self._session.proxies = {"http": None, "https": None}
        self._cookie_path = cookie_path or DEFAULT_COOKIE_PATH
        self._cookie_dict = cookie_dict
        self._csrf = None
        self._mid = None
        self._logged_in = False
        self._access_token = None  #  格式 cookie 中的 token_info.access_token，有则用 APP 投稿

        if self._cookie_dict:
            self._cookie_dict, self._csrf, self._mid = auth.login_with_cookie(self._cookie_dict)
            if self._cookie_dict:
                self._apply_cookie()
                self._logged_in = True
        elif self._cookie_path and os.path.isfile(self._cookie_path):
            loaded, token_info = auth.load_cookie_from_file(self._cookie_path)
            if loaded:
                self._cookie_dict, self._csrf, self._mid = auth.login_with_cookie(loaded)
                if self._cookie_dict:
                    self._apply_cookie()
                    self._logged_in = True
                if token_info and token_info.get("access_token"):
                    self._access_token = token_info.get("access_token")

    def _apply_cookie(self):
        if not self._session or not self._cookie_dict:
            return
        self._session.cookies.clear()
        for k, v in self._cookie_dict.items():
            self._session.cookies.set(k, v, domain=".bilibili.com")
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://member.bilibili.com/",
            "Origin": "https://member.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        })

    def login(self, use_qrcode=False, save_cookie_path=None, **kwargs):
        """
        登录。若已有有效 Cookie 则直接成功；否则若 use_qrcode=True 则扫码登录。
        :param use_qrcode: 是否使用扫码登录（无 Cookie 或 Cookie 失效时）
        :param save_cookie_path: 扫码登录成功后保存 Cookie 的路径
        :return: True 成功
        """
        if self.is_logged_in():
            return True
        if use_qrcode and self._session:
            path = save_cookie_path or self._cookie_path
            # 扫码时在 push/tmp 下生成二维码图片，便于用手机扫描
            push_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            qr_tmp_dir = os.path.join(push_dir, "tmp")
            if not os.path.isdir(qr_tmp_dir):
                os.makedirs(qr_tmp_dir)
            qrcode_image_path = os.path.join(qr_tmp_dir, "bilibili_qrcode.png")
            self._cookie_dict, self._csrf, self._mid, self._access_token = auth.login_with_qrcode(
                self._session, save_cookie_path=path, qrcode_image_path=qrcode_image_path
            )
            if self._cookie_dict:
                self._apply_cookie()
                self._logged_in = True
                return True
        return False

    def is_logged_in(self):
        if not self._logged_in or not self._cookie_dict:
            return False
        ok, _ = auth.check_cookie_valid(self._cookie_dict)
        if not ok:
            self._logged_in = False
            return False
        return True

    def upload(self, video_path, title, desc="", tid=21, tag=None, source="", cover="", no_reprint=True, dynamic="", dtime=None, **kwargs):
        """
        上传单个视频并提交稿件。
        :param video_path: 本地 mp4 路径
        :param title: 标题（≤80 字）
        :param desc: 简介
        :param tid: 分区 id，默认 21（日常），常见 160 生活、5 娱乐等
        :param tag: 标签，逗号分隔字符串或列表
        :param source: 转载来源（非原创时填）
        :param cover: 封面图 URL（可选，需先上传封面接口得到）
        :param no_reprint: 禁止转载
        :param dynamic: 粉丝动态
        :param dtime: 定时发布时间戳（10 位）
        :return: 投稿结果 dict，含 code、data（如 aid、bvid）等
        """
        if not self._session:
            raise RuntimeError("需要 requests: pip install requests")
        if not self.is_logged_in():
            msg = "未登录或 Cookie 已失效，请重新登录：\n"
            msg += "  方法1: 删除 push/bilibili/cookie.json 后，运行 --push-login 扫码重新登录\n"
            msg += "  方法2: 使用  login 扫码后，复制其生成的 cookies.json 到 push/bilibili/cookie.json"
            raise RuntimeError(msg)
        if len(title) > 80:
            raise ValueError("标题不能超过 80 字")

        tag = tag or []
        if isinstance(tag, str):
            tag = [t.strip() for t in tag.split(",") if t.strip()]
        tag_str = ",".join(tag[:12])  # B 站最多约 12 个标签

        # 1. preupload（兼容服务端返回 snake_case / camelCase）
        pre = upload.preupload(self._session, video_path)
        endpoint = pre.get("endpoint") or pre.get("endpoint")
        upos_uri = pre.get("upos_uri") or pre.get("uposUri")
        auth_header = pre.get("auth")
        biz_id = pre.get("biz_id") or pre.get("bizId")
        chunk_size = pre.get("chunk_size") or pre.get("chunkSize") or 4194304
        if not all([endpoint, upos_uri, auth_header, biz_id is not None]):
            raise RuntimeError("preupload 返回缺少必要字段: {}".format(list(pre.keys())))
        filename = os.path.basename(video_path)

        # 2. init multipart
        upload_id = upload.init_multipart(self._session, endpoint, upos_uri, auth_header)

        # 3. upload chunks + complete（返回 complete 响应，用于提交时的 filename）
        complete_resp = upload.upload_chunks(
            self._session, endpoint, upos_uri, upload_id, video_path,
            chunk_size, biz_id, filename,
        )

        # 4. videos 格式：filename 与  一致，取 upos_uri 路径的 file_stem（最后一段无扩展名）
        path_part = upos_uri.split("?")[0].replace("upos://", "")
        key = Path(path_part).stem
        if complete_resp:
            submit_key = complete_resp.get("filename") or complete_resp.get("key")
            if submit_key:
                key = submit_key if "." not in str(submit_key) else str(submit_key).rsplit(".", 1)[0]
        videos = [{"filename": key, "title": title, "desc": desc}]

        # 5. 提交稿件：有 access_token（ 登录）则用 APP 接口，否则用 Web 接口
        print("[DEBUG] 使用 {} 投稿，filename={}".format(
            "APP接口" if self._access_token else "Web接口", key
        ))
        if self._access_token:
            result = upload.submit_add_by_app(
                self._session, self._access_token,
                videos, title, tid, tag_str, desc,
                source=source, cover=cover, no_reprint=no_reprint, dynamic=dynamic, dtime=dtime,
            )
        else:
            result = upload.submit_add(
                self._session, self._csrf,
                videos, title, tid, tag_str, desc,
                source=source, cover=cover, no_reprint=no_reprint, dynamic=dynamic, dtime=dtime,
            )
        return result
