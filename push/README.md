# 推送模块 (push)

合并后的视频可选择推送到各视频平台，形成「合并 → 投稿」闭环。模块化设计，后续可扩展抖音、YouTube 等。

## 已支持平台

| 平台     | 标识                   | 说明                                         |
|----------|------------------------|----------------------------------------------|
| 哔哩哔哩 | `bilibili`             | Cookie / 扫码登录，API 单 P 投稿             |
| 哔哩哔哩 | `playwright_bilibili`  | Playwright 浏览器投稿，见 `playwright_push/` |

## 使用方式

### 1. 与合并脚本联动（推荐）

在 `merge_mp4_ffmpeg2.py` 中通过参数在合并完成后直接投稿：

```bash
# 仅合并，不推送
python merge_mp4_ffmpeg2.py mapbinlist.txt

# 合并并推送到 B 站（需已配置 Cookie 或使用 --push-login 扫码）
python merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --title "我的视频" --desc "简介"
python merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --title "生活向" --tid 160 --tag "生活,日常"
# 无 Cookie 时扫码登录（会保存到 push/bilibili/cookie.json）
python3 merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --push-login --title "标题"
```

### 2. 在代码中调用

```python
from push import get_pusher

pusher = get_pusher("bilibili", cookie_path="push/bilibili/cookie.json")
if not pusher.is_logged_in():
    pusher.login(use_qrcode=True, save_cookie_path="push/bilibili/cookie.json")
pusher.upload("/path/to/video.mp4", title="标题", desc="简介", tid=21, tag=["生活"])
```

## 扩展新平台

1. 在 `push/` 下新建目录，如 `push/youtube/`。
2. 实现 `PusherBase`（见 `push/base.py`）：`login`、`is_logged_in`、`upload`。
3. 在 `push/__init__.py` 的 `_register_builtin()` 中注册新类。
4. 在 `merge_mp4_ffmpeg2.py` 的 `--push` 分支中按需增加平台专属参数。

## 依赖

- `requests`（B 站 API 登录与上传均需要）

---

## 免责声明

**本模块仅供学习与个人使用。** 使用本工具进行视频推送时，请遵守各平台服务条款与相关法律法规；因使用产生的账号风险、内容纠纷或其它后果由使用者自行承担，作者不承担任何责任。请勿将本工具用于任何违法违规或违反平台规则之用途。
