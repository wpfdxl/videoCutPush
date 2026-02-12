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
import random
import sys
import time

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
except ImportError:
    Request = urlopen = None
    URLError = HTTPError = Exception

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
    __slots__ = ("filename", "audit_status", "reason", "success", "dede_user_id", "duration_sec")

    def __init__(self, filename, audit_status, reason, success=False, dede_user_id=None, duration_sec=None):
        self.filename = filename
        self.audit_status = audit_status  # 审核状态：passed / rejected / timeout / submitted / error
        self.reason = reason              # 成功或失败原因描述（失败时为错误原因）
        self.success = success
        self.dede_user_id = dede_user_id or ""   # 使用的 cookie 的 DedeUserID
        self.duration_sec = duration_sec        # 耗时（秒）

    def __repr__(self):
        return "UploadResult(filename={!r}, audit_status={!r}, reason={!r}, success={}, dede_user_id={!r}, duration_sec={})".format(
            self.filename, self.audit_status, self.reason, self.success, self.dede_user_id, self.duration_sec
        )


# 日志上下文（API 调用时传入 gindex/guid/version，日志会带 DedeUserID、视频名、gindex、guid、version）
_upload_log_ctx = {}


def _ulog(msg):
    """带时间戳和上下文的日志：先打时间，再打 DedeUserID/video_name/gindex/guid/version 前缀。"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    ctx = _upload_log_ctx
    parts = []
    if ctx.get("DedeUserID") is not None and ctx.get("DedeUserID") != "":
        parts.append("DedeUserID={}".format(ctx["DedeUserID"]))
    if ctx.get("video_name"):
        parts.append("video={}".format(ctx["video_name"]))
    if ctx.get("gindex") is not None:
        parts.append("gindex={}".format(ctx["gindex"]))
    if ctx.get("guid"):
        parts.append("guid={}".format(ctx["guid"]))
    if ctx.get("version") is not None and ctx.get("version") != "":
        parts.append("version={}".format(ctx["version"]))
    prefix = "[{}] ".format(" ".join(parts)) if parts else ""
    print("{} {}{}".format(ts, prefix, msg))


# ========== 可写死的变量 ==========
# 要上传的视频绝对路径
VIDEO_PATH = "/Users/xxxx/Downloads/4444.mp4"

# 标题（可选，不填则用文件名）
VIDEO_TITLE = ""

# Cookie：支持数组，多账号时按顺序重试（过期或账号限制则换下一个）
# 方式1：COOKIES_LIST 为数组，每项为一个账号的 cookie 对象（dict 或含 cookie_info 的对象）
COOKIES_LIST = []  # 留空则使用 COOKIE_FILE

# 方式2：单账号时可沿用 COOKIES_DICT / COOKIE_FILE（会转成单元素列表）
COOKIES_DICT = None
# 使用 playwright_push/cookie.json（与当前脚本同目录）
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.json")

# 上传页地址
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
# 稿件管理页：已通过（pubed）、未通过（not_pubed），轮询时来回刷新这两页看标题在哪个列表
VIDEO_MANAGE_URL_PUBED = "https://member.bilibili.com/platform/upload-manager/article?group=pubed&page=1"
VIDEO_MANAGE_URL_NOT_PUBED = "https://member.bilibili.com/platform/upload-manager/article?group=not_pubed&page=1"
# 投稿中列表，用于投稿完成后校验是否出现「进行中」（未出现则重试投稿）
IS_PUBING_URL = "https://member.bilibili.com/platform/upload-manager/article?group=is_pubing&page=1"

# 是否无头模式（False 可看到浏览器操作）
HEADLESS = False

# 上传完成后是否轮询审核结果（同步监听直到通过/不通过或超时）
POLL_AUDIT = True
# 轮询间隔（秒），略短可更快出结果
AUDIT_POLL_INTERVAL_SEC = 6
# 轮询最长时长（分钟），超时后仍会关闭浏览器
AUDIT_POLL_MAX_MINUTES = 10

# 视频上传与必填项就绪后再投稿（避免「未上传封面」等提示）
# 动态监听「上传完成」的最长时间（秒），500M 等大文件可调大，建议 30 分钟以上
UPLOAD_COMPLETE_WAIT_SEC = 1800
# 轮询间隔（秒），略短可更快检测到上传完成/封面就绪
UPLOAD_POLL_INTERVAL_SEC = 2
# 上传完成后固定等待（秒），等 B 站用视频首帧生成封面、封面框里有值后再继续
WAIT_AFTER_UPLOAD_SEC = 4
# 封面就绪后、点投稿前再等几秒，确保「立即投稿」按钮出现（封面框有值后按钮才可用）
WAIT_BEFORE_CLICK_SUBMIT_SEC = 1
# 等待「立即投稿」按钮出现的最长时间（毫秒），封面慢时需更长
SUBMIT_BTN_VISIBLE_TIMEOUT_MS = 60000
# 上传完成后，再等待封面/必填项就绪的最长时间（秒）
COVER_READY_WAIT_SEC = 1

# 可见范围（投稿前选择）：仅自己可见 / 公开 / 好友可见 等，与页面上选项文案一致，默认仅自己可见
VISIBILITY = "仅自己可见"

# 飞书机器人 webhook：Cookie 不可用时发送通知。不配置则不通知。可从环境变量 FEISHU_WEBHOOK_URL 读取
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")



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
        # 兼容尾部逗号等不标准 JSON（如 "DedeUserID": "xxx", }）
        import re
        raw = re.sub(r",\s*([}\]])", r"\1", raw)
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


def _notify_feishu_cookie_invalid(reason, dede_user_id=None):
    """Cookie 不可用时发送飞书机器人通知（需配置 FEISHU_WEBHOOK_URL）。"""
    url = (FEISHU_WEBHOOK_URL or "").strip()
    if not url or not url.startswith("http"):
        return
    if not Request or not urlopen:
        return
    try:
        text = "【B 站投稿】Cookie 不可用\n原因: {}".format(reason)
        if dede_user_id:
            text += "\nDedeUserID: {}".format(dede_user_id)
        body = json.dumps({"msg_type": "text", "content": {"text": text}}, ensure_ascii=False)
        req = Request(
            url,
            data=body.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        urlopen(req, timeout=10)
    except Exception as e:
        _ulog("飞书通知发送失败: {}".format(e))


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


def _get_submit_btn(page):
    """
    获取投稿按钮：先等「立即投稿」，超时则试「投稿」（B 站有时只显示投稿）。
    返回可点击的 locator 或 None。
    """
    for label, timeout_ms in [("立即投稿", min(25000, SUBMIT_BTN_VISIBLE_TIMEOUT_MS)), ("投稿", 10000)]:
        try:
            btn = page.get_by_text(label)
            btn.wait_for(state="visible", timeout=timeout_ms)
            return btn.first
        except Exception:
            continue
    return None


def _check_is_pubing_has_in_progress(context, timeout_sec=2):
    """
    新开 tab 打开「投稿中」列表页，先刷新该页再在 timeout_sec 内检查是否出现「进行中」。
    用于投稿完成后校验是否真的进入投稿中列表；未出现则说明可能没提交保存成功。
    """
    new_page = None
    try:
        new_page = context.new_page()
        new_page.goto(IS_PUBING_URL, wait_until="domcontentloaded", timeout=15000)
        new_page.reload(wait_until="domcontentloaded", timeout=15000)  # 投稿完成后先刷新列表再检查
        new_page.wait_for_timeout(400)  # 给列表渲染一点时间
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                text = new_page.inner_text("body")
                if "进行中" in text:
                    return True
            except Exception:
                pass
            new_page.wait_for_timeout(250)
        return False
    except Exception as e:
        _ulog("校验投稿中列表时出错: {}".format(e))
        return False
    finally:
        if new_page:
            try:
                new_page.close()
            except Exception:
                pass


def _wait_upload_complete(page):
    """
    动态监听视频上传完成：只有页面出现「上传完成」或「上传成功」且不再显示「上传中」时才继续。
    大文件（如 500M）会较久，轮询直到完成或超时。
    """
    deadline = time.time() + max(60, UPLOAD_COMPLETE_WAIT_SEC)
    interval = max(1, UPLOAD_POLL_INTERVAL_SEC)
    last_log = 0
    while time.time() < deadline:
        try:
            text = page.inner_text("body")
            # 仍在「上传中」则继续等，不提前进入下一步
            if "上传中" in text or "上传中..." in text:
                if time.time() - last_log >= 10:
                    _ulog("  视频仍在上传中，继续等待...")
                    last_log = time.time()
                time.sleep(interval)
                continue
            # 明确出现「上传完成」或「上传成功」再继续
            if "上传完成" in text or "上传成功" in text:
                return True
            # 可选：进度 100% 且无「上传中」也视为完成（部分页面文案）
            if "100%" in text and "上传中" not in text:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _has_cover_not_ready_prompt(text):
    """页面是否仍有「封面未就绪」类提示（请先上传封面、封面图未上传等）。"""
    if not text:
        return False
    prompts = (
        "请先上传封面",
        "封面图未上传",
        "封面图没识别出来",
        "封面没识别出来",
        "未上传封面",
        "请上传封面",
        "请选择封面",
    )
    for p in prompts:
        if p in text:
            return True
    return False


def _ensure_cover_from_first_frame(page):
    """
    若封面框还没图，尝试点击「使用首帧」/「截取首帧」等按钮，让 B 站用视频首帧生成封面。
    投稿前调用，避免点投稿时弹出「请先上传封面」。
    """
    try:
        for label in ("使用首帧", "截取首帧", "从视频截取", "首帧", "截取封面"):
            btn = page.get_by_text(label, exact=False)
            if btn.count() > 0:
                btn.first.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(300)
                try:
                    btn.first.click(timeout=5000)
                except Exception:
                    btn.first.click(force=True, timeout=5000)
                _ulog("已点击「{}」，等待封面生成...".format(label))
                page.wait_for_timeout(2000)  # 等封面生成并填入封面框
                return True
    except Exception as e:
        _ulog("尝试使用首帧生成封面时出错: {}".format(e))
    return False


def _has_cover_image_in_dom(page):
    """
    检测页面上是否已有封面图（img 有 src 且已加载）。
    B 站上传页封面通常在带 cover/poster 的容器内，或主区域内有尺寸合适的 img。
    """
    try:
        return page.evaluate("""() => {
            var imgs = document.querySelectorAll('img[src]');
            for (var i = 0; i < imgs.length; i++) {
                var img = imgs[i];
                if (!img.src || img.src.length < 10) continue;
                var w = img.naturalWidth || img.width || 0;
                var h = img.naturalHeight || img.height || 0;
                if (w >= 80 && h >= 60) return true;
            }
            var cover = document.querySelector('[class*="cover"] img[src], [class*="poster"] img[src]');
            if (cover && cover.src && cover.src.length > 10) return true;
            return false;
        }""")
    except Exception:
        return False


def _wait_cover_image_visible(page, timeout_sec=30):
    """
    上传完成后等待封面图真正出现：既无「封面图未上传」等提示，且 DOM 中有已加载的封面 img。
    满足条件连续 2 次才返回 True，避免刚出现又消失。
    """
    _ulog("等待封面图出现在页面（无「封面图未上传」且封面区有图）...")
    deadline = time.time() + timeout_sec
    ok_count = 0
    required_ok = 2
    interval = max(1, UPLOAD_POLL_INTERVAL_SEC)
    while time.time() < deadline:
        try:
            text = page.inner_text("body")
            if _has_cover_not_ready_prompt(text):
                ok_count = 0
                time.sleep(interval)
                continue
            if not _has_cover_image_in_dom(page):
                ok_count = 0
                time.sleep(interval)
                continue
            ok_count += 1
            if ok_count >= required_ok:
                _ulog("封面图已出现，继续投稿。")
                return True
        except Exception:
            ok_count = 0
        time.sleep(interval)
    _ulog("等待封面图出现超时（{} 秒），将尝试使用首帧并继续。".format(timeout_sec))
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


def _set_visibility_only_self(page):
    """
    在上传页设置可见范围为「仅自己可见」：展开更多设置 + JS 点击 .check-radio-v2-container。
    可在上传视频过程中或上传完成后调用。
    """
    if not VISIBILITY:
        return False
    try:
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        more_btn = page.get_by_text("更多设置", exact=False)
        if more_btn.count() > 0:
            more_btn.first.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(300)
            try:
                more_btn.first.click(timeout=6000)
            except Exception:
                more_btn.first.click(force=True, timeout=6000)
            page.wait_for_timeout(1000)
        js_ok = page.evaluate("""(targetLabel) => {
            const containers = document.querySelectorAll('.check-radio-v2-container');
            for (const c of containers) {
                if (c.textContent && c.textContent.indexOf(targetLabel) >= 0) {
                    c.click();
                    return true;
                }
            }
            return false;
        }""", VISIBILITY)
        if js_ok:
            page.wait_for_timeout(500)
            _ulog("已设置可见范围: {}.".format(VISIBILITY))
            return True
    except Exception:
        pass
    return False


def _page_has_article_with_title(page, title):
    """
    稿件管理页整页按标题匹配：是否有一条稿件的标题等于给定 title（不限于第一条）。
    """
    try:
        t = (title or "").strip()
        if not t:
            return False
        return page.evaluate("""(target) => {
            var els = document.querySelectorAll('[class*="title"], a[href*="/video/"]');
            for (var i = 0; i < els.length; i++) {
                var text = (els[i].innerText || els[i].textContent || '').trim();
                if (text === target) return true;
            }
            return false;
        }""", t)
    except Exception:
        return False


def _get_article_row_text_by_title(page, title):
    """
    稿件管理页整页按标题匹配：找到标题为 title 的那一条所在行的整行文案（含「审核中」等状态）。
    """
    try:
        t = (title or "").strip()
        if not t:
            return None
        return page.evaluate("""(target) => {
            var items = document.querySelectorAll('[class*="item"], [class*="article"], [class*="list"] > div, tr');
            for (var i = 0; i < items.length; i++) {
                var text = (items[i].innerText || items[i].textContent || '');
                if (text.indexOf(target) >= 0) return text.substring(0, 1000);
            }
            return null;
        }""", t)
    except Exception:
        return None


def wait_for_audit_result(page, title):
    """
    上传成功后轮询：已通过 tab 整页按标题匹配到本视频 → 通过；
    未通过 tab 整页按标题匹配到本视频且该条状态非「审核中」→ 未通过；审核中则继续等。
    返回 "passed" | "rejected" | "timeout"
    """
    max_seconds = max(1, AUDIT_POLL_MAX_MINUTES * 60)
    interval = max(1, AUDIT_POLL_INTERVAL_SEC)
    start = time.time()
    _ulog("正在监听审核结果（已通过/未通过 tab 整页按标题匹配，审核中不判为未通过，每 {} 秒，最长 {} 分钟）...".format(interval, AUDIT_POLL_MAX_MINUTES))
    while (time.time() - start) < max_seconds:
        try:
            # 已通过 tab：整页是否有标题=本视频
            page.goto(VIDEO_MANAGE_URL_PUBED, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            if _page_has_article_with_title(page, title):
                return "passed"
            # 未通过 tab：整页是否有标题=本视频，且该条不是「审核中」
            page.goto(VIDEO_MANAGE_URL_NOT_PUBED, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            if _page_has_article_with_title(page, title):
                row_text = _get_article_row_text_by_title(page, title)
                if row_text and "审核中" in row_text:
                    pass
                else:
                    return "rejected"
        except Exception as e:
            _ulog("轮询审核状态时出错: {}".format(e))
        time.sleep(interval)
    return "timeout"


def main(video_path_arg=None, title_arg=None, gindex=None, guid=None, version=None, cookie_file=None):
    """
    入口。可由命令行、merge_mp4_ffmpeg2 或 POST 接口调用。
    :param video_path_arg: 要上传的视频路径（不传则用脚本内 VIDEO_PATH）
    :param title_arg: 投稿标题（不传则用脚本内 VIDEO_TITLE 或文件名）
    :param gindex: 可选，接口传入的 gindex，日志会带上
    :param guid: 可选，接口传入的 guid，日志会带上
    :param version: 可选，接口传入的 version，日志会带上
    :param cookie_file: 可选，接口调用时传入的 cookie 文件路径（优先于 COOKIE_FILE）
    :return: UploadResult(filename, audit_status, reason, success, dede_user_id, duration_sec)
    """
    global _upload_log_ctx
    _upload_log_ctx = {"video_name": "", "gindex": gindex, "guid": guid, "version": version, "DedeUserID": ""}
    start_time = time.time()
    filename = ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        msg = "请先安装 playwright: pip install playwright，并执行: playwright install chromium"
        _ulog(msg)
        return UploadResult("", "error", msg, False, "", time.time() - start_time)

    video_path = os.path.abspath(video_path_arg if video_path_arg else VIDEO_PATH)
    filename = os.path.basename(video_path)
    _upload_log_ctx["video_name"] = filename
    if not os.path.isfile(video_path):
        msg = "视频文件不存在: {}".format(video_path)
        _ulog(msg)
        return UploadResult(filename, "error", msg, False, "", time.time() - start_time)

    # 接口调用时优先使用传入的 cookie_file；若路径不存在则再试当前脚本同目录的 cookie.json
    cookies_list = None
    if cookie_file:
        _dir = os.path.dirname(os.path.abspath(__file__))
        paths_to_try = [
            os.path.abspath(cookie_file) if not os.path.isabs(cookie_file) else cookie_file,
            os.path.join(_dir, "cookie.json"),
        ]
        paths_to_try = list(dict.fromkeys(paths_to_try))  # 去重
        for cookie_path in paths_to_try:
            if not os.path.isfile(cookie_path):
                _ulog("Cookie 文件不存在: {}".format(cookie_path))
                continue
            #_ulog("正在从 Cookie 文件加载: {}".format(cookie_path))
            cookies_list = load_cookies_from_file(cookie_path)
            if cookies_list:
                break
            _ulog("Cookie 文件格式无效，需包含 SESSDATA 与 bili_jct，或为数组 [{\"SESSDATA\":\"...\",\"bili_jct\":\"...\"}]。")
    if not cookies_list:
        cookies_list = get_cookies_list()
    if not cookies_list:
        msg = "未配置 Cookie。请填写 COOKIES_LIST（数组）或 COOKIE_FILE / COOKIES_DICT。"
        _ulog(msg)
        _notify_feishu_cookie_invalid(msg)
        return UploadResult(filename, "error", msg, False, "", time.time() - start_time)

    title = (title_arg if title_arg is not None else VIDEO_TITLE or "")
    if hasattr(title, "strip"):
        title = title.strip()
    title = title or os.path.splitext(filename)[0]
    last_error = None
    used_dede_user_id = ""

    # 随机打乱 cookie 顺序，避免总是用第一个；不能用再依次尝试其他
    random.shuffle(cookies_list)

    global _browser_to_close
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        _browser_to_close = browser  # 进程终止时 atexit 会关
        try:
            for idx, cookies in enumerate(cookies_list):
                _upload_log_ctx["DedeUserID"] = cookies.get("DedeUserID") or ""
                used_dede_user_id = _upload_log_ctx["DedeUserID"]
                context = None
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    )
                    context.add_cookies(cookie_dict_to_playwright(cookies))
                    page = context.new_page()

                    # 1. 打开上传页（等 dom 后短等，再等 file input 可见则尽早继续）
                    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.locator('input[type="file"]').first.wait_for(state="attached", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2000)

                    if _is_cookie_expired(page):
                        _ulog("[账号 {}] Cookie 已过期，换下一账号重试。".format(idx + 1))
                        _notify_feishu_cookie_invalid("Cookie 已过期，请重新获取后更新 cookie 文件", dede_user_id=used_dede_user_id)
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
                    # 上传视频过程中即可尝试勾选可见范围「仅自己可见」（页面出现更多设置后即可选）
                    page.wait_for_timeout(4000)
                    _set_visibility_only_self(page)
                    # 动态监听视频上传完成后再进行下一步，大文件（如 500M）会等较久
                    _ulog("等待视频上传完成（动态监听，上传中会持续等待）...")
                    if not _wait_upload_complete(page):
                        _ulog("等待上传完成超时，跳过本账号（未上传完不填表投稿）。")
                        if context:
                            context.close()
                        continue
                    page.wait_for_timeout(1000)
                    # 上传完成后固定等 N 秒，让 B 站用视频首帧截图生成封面、封面框里有值
                    wait_sec = max(0, WAIT_AFTER_UPLOAD_SEC)
                    if wait_sec > 0:
                        _ulog("等待首帧截图生成封面（{} 秒）...".format(wait_sec))
                        page.wait_for_timeout(wait_sec * 1000)
                    # 等封面与必填项就绪（封面常在上传完成后自动生成）
                    _ulog("等待封面与必填项就绪...")
                    if not _wait_cover_and_required_ready(page):
                        _ulog("等待封面就绪超时，继续尝试投稿。")
                    page.wait_for_timeout(1000)
                    # 先确认封面图真的出现在页面上，再填标题/投稿，避免点投稿时提示「封面图未上传」
                    _wait_cover_image_visible(page, timeout_sec=30)
                    page.wait_for_timeout(500)

                    # 4. 填标题
                    title_selector = 'input[placeholder*="标题"], .form-item input, textarea'
                    try:
                        page.locator(title_selector).first.fill(title)
                    except Exception:
                        pass
                    page.wait_for_timeout(800)

                    # 4.5 先点「保存」再投稿，确保视频信息提交保存
                    try:
                        save_btn = page.get_by_text("保存")
                        if save_btn.count() > 0:
                            save_btn.first.click(timeout=3000)
                            page.wait_for_timeout(1500)
                    except Exception:
                        pass

                    # 4.6 点投稿前确保封面框里有封面：先尝试「使用首帧」等，再等「请先上传封面」消失
                    _ulog("点投稿前确保封面框有封面（必要时使用首帧）...")
                    _ensure_cover_from_first_frame(page)
                    _ulog("点投稿前确认封面已就绪（无「请先上传封面」等提示）...")
                    deadline = time.time() + 60
                    ok_count = 0
                    required_ok = 2  # 连续 2 次无封面提示才继续，避免刚消失又出现
                    while time.time() < deadline:
                        try:
                            text = page.inner_text("body")
                            if _has_cover_not_ready_prompt(text):
                                ok_count = 0
                            else:
                                ok_count += 1
                                if ok_count >= required_ok:
                                    break
                        except Exception:
                            ok_count = 0
                        page.wait_for_timeout(UPLOAD_POLL_INTERVAL_SEC * 1000)
                    page.wait_for_timeout(1000)  # 封面就绪后再等 1 秒，确保封面框已填
                    # 点投稿前再确认一次封面图已在 DOM 中（可能刚点了「使用首帧」）
                    if not _has_cover_image_in_dom(page):
                        _wait_cover_image_visible(page, timeout_sec=15)
                    # 封面就绪后再等几秒，让「立即投稿」按钮出现（先上传视频 → 等封面框有值 → 再触发投稿）
                    if WAIT_BEFORE_CLICK_SUBMIT_SEC > 0:
                        _ulog("封面就绪，等待 {} 秒后点击投稿...".format(WAIT_BEFORE_CLICK_SUBMIT_SEC))
                        page.wait_for_timeout(WAIT_BEFORE_CLICK_SUBMIT_SEC * 1000)

                    # 4.7 投稿前再设一次可见范围（若上传过程中未勾选成功）
                    _set_visibility_only_self(page)

                    # 5. 点击立即投稿（若有封面上传提示则等 2 秒再点一次）
                    _ulog("等待投稿按钮出现（先试「立即投稿」，再试「投稿」）...")
                    submit_btn = _get_submit_btn(page)
                    if not submit_btn:
                        _ulog("未找到投稿按钮（立即投稿/投稿），跳过本账号。")
                        if context:
                            context.close()
                        continue
                    submit_btn.scroll_into_view_if_needed()
                    for attempt in range(2):  # 最多点两次：首次 + 遇封面提示再点一次
                        try:
                            submit_btn.click(timeout=10000)
                        except Exception:
                            submit_btn.click(force=True, timeout=10000)
                        # 条件满足即继续：每 0.5s 检查是否已进入投稿结果页，最多等 6 秒
                        for _ in range(12):
                            page.wait_for_timeout(500)
                            if _is_submit_ok(page):
                                break
                        try:
                            text = page.inner_text("body")
                            if _has_cover_not_ready_prompt(text):
                                _ulog("检测到「请先上传封面」等提示，尝试使用首帧后再重试投稿。")
                                page.keyboard.press("Escape")  # 关闭弹窗
                                page.wait_for_timeout(500)
                                _ensure_cover_from_first_frame(page)
                                page.wait_for_timeout(1500)
                                submit_btn = _get_submit_btn(page)
                                if submit_btn:
                                    submit_btn.scroll_into_view_if_needed()
                                continue
                        except Exception:
                            pass
                        break

                    if _is_account_limit(page):
                        _ulog("[账号 {}] 账号投稿限制（过于频繁或今日上限），换下一账号重试。".format(idx + 1))
                        if context:
                            context.close()
                        continue

                    if _is_submit_ok(page):
                        # 投稿后若仍出现封面未就绪/报错（如封面图没识别出来），不视为投稿完成，先等待后重试投稿
                        for _ in range(2):
                            try:
                                text = page.inner_text("body")
                                if not _has_cover_not_ready_prompt(text):
                                    break
                            except Exception:
                                break
                            _ulog("检测到封面未就绪或报错（如封面图没识别出来），不视为投稿完成，等待 5 秒后重试投稿。")
                            page.wait_for_timeout(5000)
                            submit_btn = _get_submit_btn(page)
                            if not submit_btn:
                                _ulog("重试时未找到投稿按钮。")
                                break
                            submit_btn.click(timeout=10000)
                            page.wait_for_timeout(5000)
                        # 若仍有封面报错，不进行「进行中」校验，换下一账号
                        try:
                            text = page.inner_text("body")
                            if _has_cover_not_ready_prompt(text):
                                _ulog("封面仍未就绪或报错，不进行投稿中列表校验，换下一账号重试。")
                                if context:
                                    context.close()
                                continue
                        except Exception:
                            pass
                        _ulog("投稿完成，刷新投稿中列表校验是否出现进行中（最多等 2 秒）...")
                        has_in_progress = _check_is_pubing_has_in_progress(context, timeout_sec=2)
                        if not has_in_progress:
                            _ulog("投稿后 2 秒内未在投稿中列表看到进行中，重试投稿（可能未提交保存）。")
                            try:
                                submit_btn = _get_submit_btn(page)
                                if submit_btn:
                                    submit_btn.click(timeout=10000)
                                    page.wait_for_timeout(5000)
                                    has_in_progress = _check_is_pubing_has_in_progress(context, timeout_sec=2)
                                    if has_in_progress:
                                        _ulog("重试投稿后，投稿中列表已出现进行中。")
                                else:
                                    _ulog("重试时未找到投稿按钮，无法再次点击。")
                            except Exception as e:
                                _ulog("重试投稿时出错: {}".format(e))
                        if not has_in_progress:
                            _ulog("投稿后仍未在投稿中列表看到进行中，视为未提交成功，换下一账号重试。")
                            if context:
                                context.close()
                            continue
                        _ulog("提交成功，请到 B 站创作中心查看稿件状态。")
                        audit_status = "submitted"
                        reason = "已提交成功"
                        if POLL_AUDIT:
                            result = wait_for_audit_result(page, title)
                            if result == "passed":
                                _ulog("审核结果：已通过。")
                                audit_status = "passed"
                                reason = "审核通过"
                            elif result == "rejected":
                                _ulog("审核结果：未通过/已退回，请到创作中心查看原因。")
                                audit_status = "rejected"
                                reason = "审核未通过/已退回，请到创作中心查看原因"
                            else:
                                _ulog("审核结果：超时未出结果，请到创作中心稿件管理查看。")
                                audit_status = "timeout"
                                reason = "审核监听超时未出结果，请到创作中心稿件管理查看"
                        if context:
                            context.close()
                        _browser_to_close = None
                        browser.close()
                        duration_sec = round(time.time() - start_time, 2)
                        return UploadResult(filename, audit_status, reason, success=(audit_status == "passed"), dede_user_id=used_dede_user_id, duration_sec=duration_sec)
                    if context:
                        context.close()
                except Exception as e:
                    last_error = e
                    _ulog("[账号 {}] 出错: {}".format(idx + 1, e))
                    if context:
                        try:
                            context.close()
                        except Exception:
                            pass
                    continue

            browser.close()
            _browser_to_close = None
            duration_sec = round(time.time() - start_time, 2)
            if last_error:
                msg = "投稿过程出错: {}".format(last_error)
                _ulog(msg)
                return UploadResult(filename, "error", msg, False, used_dede_user_id, duration_sec)
            msg = "所有账号均未成功（Cookie 过期或账号限制），请检查配置或稍后重试。"
            _ulog(msg)
            _notify_feishu_cookie_invalid(msg, dede_user_id=used_dede_user_id or None)
            return UploadResult(filename, "error", msg, False, used_dede_user_id, duration_sec)
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
