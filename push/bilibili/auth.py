# -*- coding: utf-8 -*-
"""
B 站登录：支持 Cookie 文件、扫码、账号密码（与  类似）。
"""
from __future__ import absolute_import

import json
import os
import re
import time

try:
    import requests
except ImportError:
    requests = None

# 登录 API 参考  / bilibili 开放接口
PASSPORT_GETKEY = "https://passport.bilibili.com/x/passport-login/web/key"
PASSPORT_QR_GET = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
PASSPORT_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"


def _ensure_requests():
    if requests is None:
        raise RuntimeError("B 站登录与上传需要 requests，请执行: pip install requests")


def load_cookie_from_file(path):
    """
    从文件加载 Cookie 与可选的 token_info（ 格式，用于 APP 投稿）。
    支持格式：
    1) 本项目的 JSON：{"SESSDATA": "xx", "bili_jct": "xx"}
    2)  的 cookies.json：{"cookie_info": {"cookies": [...]}, "token_info": {"access_token": "..."}}
    3) Netscape 或纯文本：每行 name=value 或 name=value; ...
    :return: (cookie_dict, token_info) 或 (None, None)。cookie_dict 为请求用 Cookie；token_info 为 None 或含 access_token 的 dict（有则可用 APP 投稿）
    """
    if not path or not os.path.isfile(path):
        return None, None
    with open(path, "r") as f:
        raw = f.read().strip()
    if not raw.startswith("{"):
        parsed = _parse_cookie_string(raw)
        return (parsed, None) if parsed else (None, None)
    try:
        data = json.loads(raw)
        token_info = data.get("token_info") if isinstance(data.get("token_info"), dict) else None
        #  格式：cookie_info.cookies 数组
        if "cookie_info" in data and isinstance(data["cookie_info"], dict):
            cookies = data["cookie_info"].get("cookies")
            if isinstance(cookies, list):
                out = {}
                for c in cookies:
                    if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
                        out[c["name"]] = str(c["value"])
                if out.get("SESSDATA") and out.get("bili_jct"):
                    return out, token_info
                return None, token_info
        # 本项目格式或 {"cookie": "..."}
        if "cookie" in data:
            parsed = _parse_cookie_string(data["cookie"])
            return (parsed, token_info) if parsed else (None, token_info)
        out = {}
        for k, v in data.items():
            if k in ("token_info", "cookie_info", "sso", "platform"):
                continue
            if v is not None:
                out[k] = str(v)
        if out.get("SESSDATA") and out.get("bili_jct"):
            return out, token_info
        return None, token_info
    except Exception:
        return None, None


def _parse_cookie_string(s):
    """从 Cookie 字符串解析出 SESSDATA、bili_jct 等。"""
    out = {}
    for part in re.split(r";\s*", s.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    if out.get("SESSDATA") and out.get("bili_jct"):
        return out
    return None


def cookie_string_from_dict(cookie_dict):
    """将 Cookie 字典转为请求头用的字符串。"""
    return "; ".join("{}={}".format(k, v) for k, v in cookie_dict.items() if v)


def check_cookie_valid(cookie_dict):
    """
    用 /x/web-interface/nav 检查 Cookie 是否有效。
    :return: (bool 是否有效, dict 或 None 用户信息)
    """
    _ensure_requests()
    if not cookie_dict or not cookie_dict.get("SESSDATA"):
        return False, None
    r = requests.get(
        NAV_URL,
        cookies=cookie_dict,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        },
        timeout=10,
    )
    try:
        data = r.json()
        if data.get("code") == 0 and data.get("data", {}).get("isLogin") is True:
            return True, data.get("data")
        return False, None
    except Exception:
        return False, None


def login_with_cookie(cookie_dict):
    """
    使用已有 Cookie 字典完成“登录”（仅校验并提取 csrf/mid）。
    :return: (cookie_dict, csrf, mid) 或 (None, None, None) 表示失败
    """
    ok, user = check_cookie_valid(cookie_dict)
    if not ok:
        return None, None, None
    csrf = cookie_dict.get("bili_jct") or ""
    mid = cookie_dict.get("DedeUserID") or (user.get("mid") if user else None)
    if mid is not None:
        mid = str(mid)
    return cookie_dict, csrf, mid


def login_with_qrcode(session, save_cookie_path=None, qrcode_image_path=None):
    """
    扫码登录：生成二维码 URL，轮询直到成功，将 Cookie 与 token_info 写入 save_cookie_path。
    :param session: requests.Session
    :param save_cookie_path: 成功后将 cookie 写入该文件（ 格式 JSON，包含 token_info）
    :param qrcode_image_path: 若提供，将登录链接转为二维码图片保存到该路径（需安装 qrcode）
    :return: (cookie_dict, csrf, mid, access_token) 或 (None, None, None, None) 超时/失败
    """
    _ensure_requests()
    # 生成二维码
    r = session.get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"},
        timeout=10,
    )
    try:
        j = r.json()
        if j.get("code") != 0:
            return None, None, None, None
        qrcode_url = j.get("data", {}).get("url", "")
        qrcode_key = j.get("data", {}).get("qrcode_key", "")
    except Exception:
        return None, None, None, None

    if not qrcode_url or not qrcode_key:
        return None, None, None, None

    print("请使用 B 站 App 或浏览器扫描以下链接登录：")
    print(qrcode_url)
    print("(或打开 https://passport.bilibili.com/qrcode/h5?qrcode={} )".format(qrcode_key))
    if qrcode_image_path:
        try:
            from .. import qrcode_util
            saved = qrcode_util.save_qrcode_image(qrcode_url, qrcode_image_path)
            if saved:
                print("二维码图片已保存至: {}".format(saved))
            else:
                print("(未安装 qrcode 时无法生成二维码图片，请 pip install qrcode[pillow])")
        except Exception as e:
            print("生成二维码图片失败: {}".format(e))

    # 轮询
    poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    for _ in range(120):
        time.sleep(2)
        r2 = session.get(
            poll_url,
            params={"qrcode_key": qrcode_key},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"},
            timeout=10,
        )
        try:
            j2 = r2.json()
            code = j2.get("data", {}).get("code")
            if code == 0:
                # 成功，cookie 在 session 里
                url = j2.get("data", {}).get("url", "")
                session.get(url, allow_redirects=True, timeout=10)
                cookie_dict = session.cookies.get_dict(domain=".bilibili.com")
                if not cookie_dict:
                    cookie_dict = dict(session.cookies.get_dict())
                cookie_dict = {k: v for k, v in cookie_dict.items() if v}
                
                # 获取 access_token（用于 APP 接口投稿）
                access_token = None
                token_info = None
                try:
                    token_resp = session.post(
                        "https://passport.bilibili.com/x/passport-login/oauth2/access_token",
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"},
                        timeout=10,
                    )
                    token_data = token_resp.json()
                    if token_data.get("code") == 0:
                        token_info = token_data.get("data", {}).get("token_info", {})
                        access_token = token_info.get("access_token")
                        if access_token:
                            print("已获取 access_token，将使用 APP 接口投稿（成功率更高）")
                except Exception as e:
                    print("获取 access_token 失败（将使用 Web 接口投稿）: {}".format(e))
                
                # 保存为  格式（包含 token_info）
                if save_cookie_path:
                    try:
                        # 构建  格式的 cookies.json
                        cookies_list = []
                        for name, value in cookie_dict.items():
                            cookies_list.append({
                                "name": name,
                                "value": value,
                                "http_only": 0,
                                "secure": 0,
                                "expires": int(time.time()) + 15552000,  # 180天
                            })
                        
                        save_data = {
                            "cookie_info": {
                                "cookies": cookies_list,
                                "domains": [
                                    ".bilibili.com",
                                    ".biligame.com",
                                    ".bigfun.cn",
                                    ".bigfunapp.cn",
                                    ".dreamcast.hk"
                                ]
                            },
                            "sso": [
                                "https://passport.bilibili.com/api/v2/sso",
                                "https://passport.biligame.com/api/v2/sso",
                                "https://passport.bigfunapp.cn/api/v2/sso"
                            ],
                            "platform": "BiliTV"
                        }
                        
                        if token_info:
                            save_data["token_info"] = token_info
                        
                        with open(save_cookie_path, "w") as f:
                            json.dump(save_data, f, indent=2)
                        print("登录信息已保存至: {}".format(save_cookie_path))
                    except Exception as e:
                        print("保存登录信息失败: {}".format(e))
                
                cookie_dict_ret, csrf, mid = login_with_cookie(cookie_dict)
                return cookie_dict_ret, csrf, mid, access_token
            if code == 86038:
                print("二维码已过期，请重试。")
                return None, None, None, None
            if code == 86090:
                continue  # 已扫码未确认
        except Exception:
            continue
    print("扫码登录超时。")
    return None, None, None, None
