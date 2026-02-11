# -*- coding: utf-8 -*-
"""
B 站视频上传 - 通过 Python 调用 Playwright 实现（对应 MCP 文档中的流程）。
支持：视频路径、Cookie 变量/文件写死，手动抓 Cookie 后 set 上即可免登录。
Python 3.7+，需安装 playwright 并执行 playwright install chromium。
"""
from __future__ import print_function

import atexit
import json
import os
import sys
import time

_browser_to_close = None


def _ensure_browser_closed():
    """进程退出或异常时确保关闭浏览器。"""
    global _browser_to_close
    if _browser_to_close is not None:
        try:
            _browser_to_close.close()
        except Exception:
            pass
        _browser_to_close = None


atexit.register(_ensure_browser_closed)


class UploadResult(object):
    """上传/投稿结果对象，供调用方使用。"""
    __slots__ = ("filename", "audit_status", "reason", "success")

    def __init__(self, filename, audit_status, reason, success=False):
        self.filename = filename       # 文件名（视频 basename）
        self.audit_status = audit_status  # 审核状态：passed / rejected / timeout / submitted / error
        self.reason = reason           # 成功或失败原因描述
        self.success = success         # 是否成功（提交且审核通过为 True）

    def __repr__(self):
        return "UploadResult(filename={!r}, audit_status={!r}, reason={!r}, success={})".format(
            self.filename, self.audit_status, self.reason, self.success
        )


# ========== 可写死的变量 ==========
# 要上传的视频绝对路径
VIDEO_PATH = "/Users/xxxx/Downloads/4444.mp4"

# 标题（可选，不填则用文件名）
VIDEO_TITLE = ""

# Cookie：支持数组，多账号时按顺序重试（过期或账号限制则换下一个）
# 方式1：COOKIES_LIST 为数组，每项为一个账号的 cookie 对象（dict 或含 cookie_info 的对象）
COOKIES_LIST = [
    # 账号1
    {
        "SESSDATA": "33f02fef%2C1786325952%2C7a906%2A21CjDGi5LVu1p786bFV2GhLP5vGzaPcl-UyFOyr4VEA8wfQxOJrXGcdMRJq04qriIL-y0SVjNRRVByMENWbE1MU0t6Z2pQcGVVeHRxR2xoN2RnVDVwNGNBdTBvcmVmX2RRNjlXVXNBajhnTEZZM1BocWtRYWpFY2VzZmZhOVAxX0xRdDNZTklDOVl3IIEC",
        "bili_jct": "85dfc90d754e01b1152b638387cdbe32",
        "DedeUserID": "412653959",
    },
    # 账号2（可选，cookie 过期或上传限制时自动换此账号重试）
    # {"SESSDATA": "...", "bili_jct": "...", "DedeUserID": "..."},
]

# 方式2：单账号时可沿用 COOKIES_DICT / COOKIE_FILE（会转成单元素列表）
COOKIES_DICT = None
COOKIE_FILE = None  # 例如 "push/bilibili/cookie.json"

# 上传页地址
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
# 稿件管理页：已通过（pubed）、未通过（not_pubed），轮询时来回刷新这两页看标题在哪个列表
VIDEO_MANAGE_URL_PUBED = "https://member.bilibili.com/platform/upload-manager/article?group=pubed&page=1"
VIDEO_MANAGE_URL_NOT_PUBED = "https://member.bilibili.com/platform/upload-manager/article?group=not_pubed&page=1"

# 是否无头模式（False 可看到浏览器操作）
HEADLESS = False

# 上传完成后是否轮询审核结果（同步监听直到通过/不通过或超时）
POLL_AUDIT = True
# 轮询间隔（秒）
AUDIT_POLL_INTERVAL_SEC = 15
# 轮询最长时长（分钟），超时后仍会关闭浏览器
AUDIT_POLL_MAX_MINUTES = 6

# 视频上传与必填项就绪后再投稿（避免「未上传封面」等提示）
# 等待「上传完成」的最长时间（秒），大文件可调大
UPLOAD_COMPLETE_WAIT_SEC = 600
# 轮询间隔（秒）
UPLOAD_POLL_INTERVAL_SEC = 3
# 上传完成后固定等待（秒），等 B 站用视频首帧生成封面、封面框里有值后再继续（建议 5–10 秒）
WAIT_AFTER_UPLOAD_SEC = 10
# 封面就绪后、点投稿前再等几秒，确保「立即投稿」按钮出现（封面框有值后按钮才可用）
WAIT_BEFORE_CLICK_SUBMIT_SEC = 2
# 等待「立即投稿」按钮出现的最长时间（毫秒），封面慢时需更长
SUBMIT_BTN_VISIBLE_TIMEOUT_MS = 60000
# 上传完成后，再等待封面/必填项就绪的最长时间（秒）
COVER_READY_WAIT_SEC = 1



def _normalize_cookie_item(item):
    """将单个 cookie 项（dict 或含 cookie_info 的对象）转为 name->value 字典。"""
    if not item or not isinstance(item, dict):
        return None
    # cookie_info.cookies 数组格式
    if "cookie_info" in item and isinstance(item.get("cookie_info"), dict):
        cookies = item["cookie_info"].get("cookies")
        if isinstance(cookies, list):
            out = {}
            for c in cookies:
                if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
                    out[c["name"]] = str(c["value"])
            if out.get("SESSDATA") and out.get("bili_jct"):
                return out
            return None
    # 简单 dict：SESSDATA, bili_jct, DedeUserID
    out = {}
    for k, v in item.items():
        if k in ("token_info", "cookie_info", "sso", "platform"):
            continue
        if v is not None:
            out[k] = str(v)
    if out.get("SESSDATA") and out.get("bili_jct"):
        return out
    return None


def load_cookies_from_file(path):
    """从文件加载 Cookie。若文件是数组则返回多个 name->value 字典的列表，否则返回单元素列表或 None。"""
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        data = json.loads(raw)
    except Exception:
        return None
    # 文件是数组：[{...}, {...}]
    if isinstance(data, list):
        result = []
        for item in data:
            c = _normalize_cookie_item(item) if isinstance(item, dict) else None
            if c:
                result.append(c)
        return result if result else None
    # 单对象
    if not isinstance(data, dict):
        return None
    # cookie_info.cookies 数组
    if "cookie_info" in data and isinstance(data.get("cookie_info"), dict):
        cookies = data["cookie_info"].get("cookies")
        if isinstance(cookies, list):
            out = {}
            for c in cookies:
                if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
                    out[c["name"]] = str(c["value"])
            if out.get("SESSDATA") and out.get("bili_jct"):
                return [out]
            return None
    # "cookie": "SESSDATA=xx; bili_jct=yy"
    if "cookie" in data and isinstance(data.get("cookie"), str):
        out = {}
        for part in data["cookie"].split(";"):
            part = part.strip()
            if "=" in part:
                key, val = part.split("=", 1)
                out[key.strip()] = val.strip()
        if out.get("SESSDATA") and out.get("bili_jct"):
            return [out]
        return None
    out = {}
    for k, v in data.items():
        if k in ("token_info", "cookie_info", "sso", "platform"):
            continue
        if v is not None:
            out[k] = str(v)
    if out.get("SESSDATA") and out.get("bili_jct"):
        return [out]
    return None


def cookie_dict_to_playwright(cookie_dict):
    """将 {name: value} 转为 Playwright add_cookies 需要的列表。"""
    if not cookie_dict:
        return []
    out = []
    for name, value in cookie_dict.items():
        if not name or value is None:
            continue
        out.append({
            "name": name,
            "value": str(value),
            "domain": ".bilibili.com",
            "path": "/",
        })
    return out


def get_cookies_list():
    """返回 Cookie 列表，每项为一个账号的 name->value 字典。支持 COOKIES_LIST 数组或 COOKIE_FILE/COOKIES_DICT。"""
    if COOKIES_LIST:
        result = []
        for item in COOKIES_LIST:
            c = _normalize_cookie_item(item) if isinstance(item, dict) else None
            if c:
                result.append(c)
        if result:
            return result
    if COOKIES_DICT and COOKIES_DICT.get("SESSDATA") and COOKIES_DICT.get("bili_jct"):
        return [COOKIES_DICT]
    if COOKIE_FILE:
        return load_cookies_from_file(COOKIE_FILE)
    return None


def _is_cookie_expired(page):
    """根据当前页 URL 或文案判断是否未登录（Cookie 过期）。"""
    try:
        url = page.url
        if "passport" in url or "login" in url.lower():
            return True
        text = page.inner_text("body")[:2000]
        if "请登录" in text or "登录后" in text or "未登录" in text:
            return True
    except Exception:
        pass
    return False


def _is_account_limit(page):
    """根据页面文案判断是否账号限制（投稿过于频繁、今日上限等）。"""
    try:
        text = page.inner_text("body")
        if "投稿过于频繁" in text or "过于频繁" in text:
            return True
        if "今日投稿" in text and ("达" in text or "上限" in text or "限制" in text):
            return True
        if "已达上限" in text or "频率" in text and "限制" in text:
            return True
    except Exception:
        pass
    return False


def _is_submit_ok(page):
    """是否提交成功（稿件处理/审核中）。"""
    try:
        text = page.inner_text("body")
        return "稿件" in text or "审核" in text or "处理" in text
    except Exception:
        return False


def _wait_upload_complete(page):
    """等待页面出现「上传完成」或类似文案，表示视频已上传完。"""
    deadline = time.time() + max(10, UPLOAD_COMPLETE_WAIT_SEC)
    interval = max(1, UPLOAD_POLL_INTERVAL_SEC)
    while time.time() < deadline:
        try:
            text = page.inner_text("body")
            if "上传完成" in text or "上传成功" in text or "100%" in text:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _has_cover_not_ready_prompt(text):
    """页面是否仍有「封面未就绪」类提示（封面图未上传、未上传封面等）。"""
    if not text:
        return False
    prompts = (
        "封面图未上传",
        "未上传封面",
        "请上传封面",
        "请选择封面",
    )
    for p in prompts:
        if p in text:
            return True
    return False


def _wait_cover_and_required_ready(page):
    """等待封面识别/生成就绪：页面连续若干次不再出现「封面图未上传」等提示后再继续。"""
    deadline = time.time() + max(5, COVER_READY_WAIT_SEC)
    interval = max(1, UPLOAD_POLL_INTERVAL_SEC)
    required_ok_count = 2  # 连续 2 次检查无封面提示才认为就绪
    ok_count = 0
    while time.time() < deadline:
        try:
            text = page.inner_text("body")
            if _has_cover_not_ready_prompt(text):
                ok_count = 0
                time.sleep(interval)
                continue
            ok_count += 1
            if ok_count >= required_ok_count:
                return True
        except Exception:
            ok_count = 0
        time.sleep(interval)
    return False


def wait_for_audit_result(page, title):
    """
    上传成功后轮询：分别刷新「已通过」(group=pubed) 和「未通过」(group=not_pubed) 页，
    看刚上传的视频标题出现在哪一页 → 在已通过即通过，在未通过即未通过。
    返回 "passed" | "rejected" | "timeout"
    """
    max_seconds = max(1, AUDIT_POLL_MAX_MINUTES * 60)
    interval = max(1, AUDIT_POLL_INTERVAL_SEC)
    start = time.time()
    print("正在监听审核结果（轮流刷新「已通过」与「未通过」页，看本视频标题在哪个列表，每 {} 秒，最长 {} 分钟）...".format(interval, AUDIT_POLL_MAX_MINUTES))
    while (time.time() - start) < max_seconds:
        try:
            # 先看「已通过」列表里有没有本视频标题
            page.goto(VIDEO_MANAGE_URL_PUBED, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            text_pubed = page.inner_text("body")
            if title in text_pubed:
                return "passed"
            # 再看「未通过」列表里有没有本视频标题
            page.goto(VIDEO_MANAGE_URL_NOT_PUBED, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            text_not_pubed = page.inner_text("body")
            if title in text_not_pubed:
                return "rejected"
        except Exception as e:
            print("轮询审核状态时出错: {}".format(e))
        time.sleep(interval)
    return "timeout"


def main(video_path_arg=None, title_arg=None):
    """
    入口。可由命令行或 merge_mp4_ffmpeg2 调用。
    :param video_path_arg: 要上传的视频路径（不传则用脚本内 VIDEO_PATH）
    :param title_arg: 投稿标题（不传则用脚本内 VIDEO_TITLE 或文件名）
    :return: UploadResult(filename, audit_status, reason, success)
    """
    filename = ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        msg = "请先安装 playwright: pip install playwright，并执行: playwright install chromium"
        print(msg)
        return UploadResult("", "error", msg, False)

    video_path = os.path.abspath(video_path_arg if video_path_arg else VIDEO_PATH)
    filename = os.path.basename(video_path)
    if not os.path.isfile(video_path):
        msg = "视频文件不存在: {}".format(video_path)
        print(msg)
        return UploadResult(filename, "error", msg, False)

    cookies_list = get_cookies_list()
    if not cookies_list:
        msg = "未配置 Cookie。请填写 COOKIES_LIST（数组）或 COOKIE_FILE / COOKIES_DICT。"
        print(msg)
        return UploadResult(filename, "error", msg, False)

    title = (title_arg if title_arg is not None else VIDEO_TITLE or "")
    if hasattr(title, "strip"):
        title = title.strip()
    title = title or os.path.splitext(filename)[0]
    last_error = None

    global _browser_to_close
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        _browser_to_close = browser  # 进程终止时 atexit 会关
        try:
            for idx, cookies in enumerate(cookies_list):
                context = None
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                    context.add_cookies(cookie_dict_to_playwright(cookies))
                    page = context.new_page()

                    # 1. 打开上传页
                    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(4000)

                    if _is_cookie_expired(page):
                        print("[账号 {}] Cookie 已过期，换下一账号重试。".format(idx + 1))
                        if context:
                            context.close()
                        continue

                    # 2. 使 file input 可见
                    page.evaluate("""
                    () => {
                        document.querySelectorAll('input[type=file]').forEach(el => {
                            el.style.display = 'block';
                            el.style.visibility = 'visible';
                            el.style.opacity = '1';
                            el.style.position = 'fixed';
                            el.style.left = '0';
                            el.style.top = '0';
                            el.style.width = '300px';
                            el.style.height = '100px';
                            el.style.zIndex = '999999';
                        });
                    }
                    """)

                    # 3. 上传文件
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(video_path)
                    # 等视频上传完成再继续，避免点投稿时提示「未上传封面」
                    print("等待视频上传完成...")
                    if not _wait_upload_complete(page):
                        print("等待上传完成超时，继续尝试填表投稿。")
                    page.wait_for_timeout(2000)
                    # 上传完成后固定等 N 秒，让 B 站用视频首帧截图生成封面、封面框里有值
                    wait_sec = max(0, WAIT_AFTER_UPLOAD_SEC)
                    if wait_sec > 0:
                        print("等待首帧截图生成封面（{} 秒）...".format(wait_sec))
                        page.wait_for_timeout(wait_sec * 1000)
                    # 等封面与必填项就绪（封面常在上传完成后自动生成）
                    print("等待封面与必填项就绪...")
                    if not _wait_cover_and_required_ready(page):
                        print("等待封面就绪超时，继续尝试投稿。")
                    page.wait_for_timeout(1500)

                    # 4. 填标题
                    title_selector = 'input[placeholder*="标题"], .form-item input, textarea'
                    try:
                        page.locator(title_selector).first.fill(title)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)

                    # 4.5 先点「保存」再投稿，确保视频信息提交保存
                    try:
                        save_btn = page.get_by_text("保存")
                        if save_btn.count() > 0:
                            save_btn.first.click(timeout=3000)
                            page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    # 4.6 点投稿前再等封面就绪，与封面识别同步，避免「封面图未上传」导致上传失败
                    print("点投稿前确认封面已就绪...")
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        try:
                            text = page.inner_text("body")
                            if not _has_cover_not_ready_prompt(text):
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(UPLOAD_POLL_INTERVAL_SEC * 1000)
                    page.wait_for_timeout(1500)
                    # 封面就绪后再等几秒，让「立即投稿」按钮出现（先上传视频 → 等封面框有值 → 再触发投稿）
                    if WAIT_BEFORE_CLICK_SUBMIT_SEC > 0:
                        print("封面就绪，等待 {} 秒后点击投稿...".format(WAIT_BEFORE_CLICK_SUBMIT_SEC))
                        page.wait_for_timeout(WAIT_BEFORE_CLICK_SUBMIT_SEC * 1000)

                    # 5. 点击立即投稿（若有封面上传提示则等 2 秒再点一次）
                    submit_btn = page.get_by_text("立即投稿")
                    submit_btn.wait_for(state="visible", timeout=SUBMIT_BTN_VISIBLE_TIMEOUT_MS)
                    submit_btn.scroll_into_view_if_needed()
                    for attempt in range(2):  # 最多点两次：首次 + 遇封面提示再点一次
                        try:
                            submit_btn.click(timeout=10000)
                        except Exception:
                            submit_btn.click(force=True, timeout=10000)
                        page.wait_for_timeout(5000)
                        try:
                            text = page.inner_text("body")
                            if _has_cover_not_ready_prompt(text):
                                print("检测到封面未就绪提示，等待 2 秒后再次点击投稿。")
                                page.wait_for_timeout(2000)
                                submit_btn.scroll_into_view_if_needed()
                                continue
                        except Exception:
                            pass
                        break

                    if _is_account_limit(page):
                        print("[账号 {}] 账号投稿限制（过于频繁或今日上限），换下一账号重试。".format(idx + 1))
                        if context:
                            context.close()
                        continue

                    if _is_submit_ok(page):
                        print("提交成功，请到 B 站创作中心查看稿件状态。")
                        audit_status = "submitted"
                        reason = "已提交成功"
                        if POLL_AUDIT:
                            result = wait_for_audit_result(page, title)
                            if result == "passed":
                                print("审核结果：已通过。")
                                audit_status = "passed"
                                reason = "审核通过"
                            elif result == "rejected":
                                print("审核结果：未通过/已退回，请到创作中心查看原因。")
                                audit_status = "rejected"
                                reason = "审核未通过/已退回，请到创作中心查看原因"
                            else:
                                print("审核结果：超时未出结果，请到创作中心稿件管理查看。")
                                audit_status = "timeout"
                                reason = "审核监听超时未出结果，请到创作中心稿件管理查看"
                        if context:
                            context.close()
                        _browser_to_close = None
                        browser.close()
                        return UploadResult(filename, audit_status, reason, success=(audit_status == "passed"))
                    if context:
                        context.close()
                except Exception as e:
                    last_error = e
                    print("[账号 {}] 出错: {}".format(idx + 1, e))
                    if context:
                        try:
                            context.close()
                        except Exception:
                            pass
                    continue

            browser.close()
            _browser_to_close = None
            if last_error:
                msg = "投稿过程出错: {}".format(last_error)
                print(msg)
                return UploadResult(filename, "error", msg, False)
            msg = "所有账号均未成功（Cookie 过期或账号限制），请检查配置或稍后重试。"
            print(msg)
            return UploadResult(filename, "error", msg, False)
        finally:
            _ensure_browser_closed()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="B 站 Playwright 上传（学习使用，无责）")
    ap.add_argument("--video", "-v", default=None, help="要上传的视频路径（不传则用脚本内 VIDEO_PATH）")
    ap.add_argument("--title", "-t", default=None, help="投稿标题（不传则用脚本内 VIDEO_TITLE 或文件名）")
    a = ap.parse_args()
    result = main(video_path_arg=a.video, title_arg=a.title)
    if not result.success:
        sys.exit(1)
