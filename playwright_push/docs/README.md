# Playwright 方式上传 B 站

通过 **Python 调用 Playwright** 实现 B 站视频上传，流程与 [docs/bilibili_upload_mcp_calls.md](docs/bilibili_upload_mcp_calls.md) 中 MCP 工具调用一致，但无需 MCP，本地运行即可。

- **Python 3.7+**
- 视频路径、Cookie 可写死为变量，或从文件读 Cookie
- **免登录**：手动抓必要 Cookie 填到脚本/文件里即可直接上传
- **Cookie 为数组**：支持多账号，Cookie 过期或账号投稿限制时**自动换下一个重试**
- **上传完成后自动关闭浏览器**，无需手动关
- **审核结果监听**：上传成功后可选**同步轮询**稿件管理页，直到审核通过/不通过或超时
- **被 merge_mp4_ffmpeg2 调用**：合并视频后可用 `--push playwright_bilibili --title "标题"` 自动调用本脚本上传

## 安装

```bash
cd playwright_push
pip install -r requirements.txt
playwright install chromium
```

## 配置

### Cookie：支持数组（多账号自动重试）

**推荐**：使用 `COOKIES_LIST` 数组，每项为一个账号的 cookie 对象。若当前账号 **Cookie 过期** 或 **投稿限制**（过于频繁/今日上限），会自动换下一个账号重试。

```python
COOKIES_LIST = [
    {"SESSDATA": "账号1的SESSDATA", "bili_jct": "账号1的bili_jct", "DedeUserID": "账号1的DedeUserID"},
    {"SESSDATA": "账号2的...", "bili_jct": "...", "DedeUserID": "..."},
]
```

也可沿用单账号方式（会转成单元素列表）：

- `COOKIES_DICT`：单个 dict
- `COOKIE_FILE`：JSON 文件路径；若文件内容是**数组** `[{...}, {...}]`，会按顺序作为多账号重试

## 如何抓 Cookie（免登录）

1. 浏览器打开 [bilibili.com](https://www.bilibili.com) 并登录。
2. F12 打开开发者工具 → **Application**（或 应用程序）→ 左侧 **Cookies** → 选 `https://www.bilibili.com`。
3. 找到并复制以下字段的值：
   - **SESSDATA**
   - **bili_jct**
   - **DedeUserID**（可选但建议）
4. 填到脚本的 `COOKIES_LIST`（数组）或 `COOKIES_DICT` / `COOKIE_FILE`。

填好后运行脚本即可直接打开创作中心上传页并上传，无需再在 Playwright 里登录。

## 运行

```bash
python upload_bilibili.py
# 或指定视频与标题（供 merge_mp4_ffmpeg2 调用或命令行使用）
python upload_bilibili.py --video /path/to/video.mp4 --title "投稿标题"
```

- 上传成功后会**自动关闭浏览器**。
- **审核监听**：默认开启 `POLL_AUDIT`，会定期打开稿件管理页轮询刚上传视频的审核状态，直到「审核通过」「审核不通过」或超时（可配置 `AUDIT_POLL_INTERVAL_SEC`、`AUDIT_POLL_MAX_MINUTES`）；关闭则设 `POLL_AUDIT = False`。
- 默认有头模式；无头在脚本中设 `HEADLESS = True`。
- 多账号时：Cookie 过期或账号限制会打印提示并换下一账号重试，全部失败则退出。

### POST 接口（合并 + 推送）

提供 HTTP 接口：先按 `merge_mp4_ffmpeg2` 逻辑将多段 mp4 合并为一个，再推送到 B 站。

```bash
python3 -m playwright_push.api_push --host 0.0.0.0 --port 8188
```

- **路径**：`POST /push/playwright_bilibili`
- **请求体**：JSON，必填 `videos`（mp4 路径或 URL 数组），可选 `gindex`、`guid`、`version`、`retry`、`reencode`、`title`
- **响应**：`code=0` 仅当审核状态为「已通过」或「未通过」；`code=-100` 为合并前/合并报错；`code=-200` 为 Cookie 错误、push 失败等，失败原因在 `data[0].error_reason`
- **Cookie**：使用同目录 `cookie.json`，多账号时随机取一个，不可用再试其他

完整入参、响应结构、业务码与示例见 **[docs/api_push.md](docs/api_push.md)**。

---

### 被 merge_mp4_ffmpeg2 调用

在项目根目录执行合并并推送：

```bash
python merge_mp4_ffmpeg2.py mapbinlist.txt --push playwright_bilibili --title "我的视频"
```

合并完成后会自动调用本目录下的 `upload_bilibili.py`，传入合并后的视频路径与标题。Cookie 等仍在本脚本内配置（`COOKIES_LIST` / `COOKIE_FILE`）。

## 流程说明（与 MCP 文档对应）

| 步骤 | 说明 |
|------|------|
| 1 | 打开 B 站创作中心上传页（已通过 set Cookie 免登录） |
| 2 | `evaluate` 使 `input[type=file]` 可见 |
| 3 | `set_input_files` 上传本地视频 |
| 4 | 填写标题 |
| 5 | 点击「立即投稿」 |
| 6 | 根据页面文案确认是否进入稿件处理/审核 |

详见 [docs/bilibili_upload_mcp_calls.md](docs/bilibili_upload_mcp_calls.md)。

---

## 免责声明

**本脚本仅供学习与个人使用。** 使用本工具上传视频时，请遵守 B 站等服务条款与相关法律法规；因使用本工具产生的账号风险、内容纠纷或其它后果由使用者自行承担，作者不承担任何责任。请勿将本工具用于任何违法违规或违反平台规则之用途。
