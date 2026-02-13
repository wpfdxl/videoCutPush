# videoCutPush

MP4 小工具：**按列表文件合并**（ffmpeg 不重编码 / MoviePy 重编码压缩）、**推送到视频平台**（如 B 站，可选）。

## 环境

- Python 3.7+
- 系统安装 ffmpeg（所有脚本都依赖）

```bash
# macOS
brew install ffmpeg
```

## 二、按列表文件合并 MP4

列表格式与 ffmpeg concat 一致，每行：`file 'path_or_url'`。示例见 `mapbinlist.txt`。

### 2.1 不重编码：merge_mp4_ffmpeg.py（推荐）

使用 ffmpeg concat + `-c copy`，不重新编码，速度快、无损。**无需 moviepy/requests，只需系统 ffmpeg。**

```bash
python merge_mp4_ffmpeg.py mapbinlist.txt -o merged_output.mp4
python merge_mp4_ffmpeg.py /path/to/list.txt -o out.mp4 --ffmpeg /usr/local/bin/ffmpeg
```

| 参数 | 说明 |
|------|------|
| `list_file` | 列表文件路径（如 mapbinlist.txt） |
| `-o, --output` | 输出 mp4 路径（不传则写入 `tmp/merged_output.mp4`） |
| `--ffmpeg` | ffmpeg 命令或可执行路径（默认 ffmpeg） |

```python
from merge_mp4_ffmpeg import merge_by_concat_list

out = merge_by_concat_list("mapbinlist.txt", "merged_output.mp4")
```

### 2.2 工程化版：merge_mp4_ffmpeg2.py（推荐用于批量/远程）

在 2.1 基础上工程化：**列表来源**可为本地文件或公网 URL；**所有产出**进 `tmp/`，每次运行单独目录；**临时文件**（分片、concat 列表、中间合并）结束后自动删除，仅保留最终合并视频。需 `requests`（列表或分片为 URL 时）。

- **列表**：`list_source` 可为本地路径（如 `mapbinlist.txt`）或 `http(s)://` URL，自动拉取内容解析。
- **工作目录**：`tmp/merge_YYYYMMDD_HHMMSS/`，内含下载分片与合并结果。
- **清理**：默认删除分片、`concat_list.txt`、`merged_raw.mp4`，只保留最终 mp4；`--keep-tmp` 可保留临时文件。

```bash
# 本地列表
python merge_mp4_ffmpeg2.py mapbinlist.txt

# 公网列表 URL
python merge_mp4_ffmpeg2.py "https://example.com/mapbinlist.txt"

# 不指定 -o 时，输出为 tmp/merge_YYYYMMDD_HHMMSS/<列表内容MD5>.mp4（同列表同文件名）
python merge_mp4_ffmpeg2.py mapbinlist.txt -o /path/to/final.mp4

# 保留临时文件（调试用）
python merge_mp4_ffmpeg2.py mapbinlist.txt --keep-tmp

# 合并后重编码（B 站等严格时间戳场景）
python merge_mp4_ffmpeg2.py mapbinlist.txt --reencode
```

| 参数 | 说明 |
|------|------|
| `list_source` | 列表文件路径或公网 URL，每行 `file 'path_or_url'` |
| `-o, --output` | 输出 mp4 路径（不传则按列表内容 MD5 命名：`tmp/<run_id>/<md5>.mp4`，同列表唯一） |
| `--ffmpeg` | ffmpeg 命令或可执行路径（默认 ffmpeg） |
| `--keep-tmp` | 保留临时分片与中间文件（默认删除） |
| `--no-fix-timestamps` | 不做 remux 修复时间戳 |
| `--reencode` | 合并后完整重编码，兼容 B 站等平台 |
| `--push` | 合并后推送到平台：`bilibili`（API 投稿）、`playwright_bilibili`（Playwright 浏览器投稿，见 `playwright_push/`）（不传则不推送） |
| `--push-cookie` | 推送用 Cookie 文件路径（B 站默认 `push/bilibili/cookie.json`；playwright_bilibili 使用 playwright_push 内配置） |
| `--push-login` | 推送前扫码登录（仅 `bilibili`；playwright_bilibili 需在 playwright_push 中配置 Cookie） |
| `--title` | 投稿标题（与 `--push` 同用时必填，≤80 字） |
| `--desc` | 投稿简介 |
| `--tid` | B 站分区 id（默认 21 日常，160 生活、5 娱乐等） |
| `--tag` | B 站标签，逗号分隔 |

### 2.3 重编码压缩：merge_mp4_moviepy.py

从列表文件读取，用 MoviePy 按顺序合并并**重新编码**，可降低码率减小体积。支持列表中的 URL（会先下载到临时目录再合并）。需安装 `moviepy`、`requests`。

```bash
python merge_mp4_moviepy.py mapbinlist.txt -o merged.mp4
python merge_mp4_moviepy.py /path/to/list.txt -o out.mp4 -b 500k --audio-bitrate 128k
```

| 参数 | 说明 |
|------|------|
| `list_file` | 列表文件路径（默认同目录下 mapbinlist.txt） |
| `-o, --output` | 输出 mp4 路径（不传则写入 `tmp/merged.mp4`） |
| `-b, --bitrate` | 视频码率，如 800k、500k（默认 800k） |
| `--audio-bitrate` | 音频码率（默认 128k） |

```python
from merge_mp4_moviepy import merge_mp4_from_list

out = merge_mp4_from_list("mapbinlist.txt", "merged.mp4", bitrate="800k", audio_bitrate="128k")
```

---

## 三、推送到视频平台

合并完成后可选择将视频推送到 B 站等平台（参考 [](https://github.com/wpfdxl/) 的登录与投稿能力）。**不传 `--push` 则不推送**，后续可扩展其他平台。

### 3.1 与合并脚本联动（推荐）

```bash
# 合并并推送到 B 站（API 投稿，需 Cookie 或 --push-login 扫码）
python merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --title "我的视频" --desc "简介"
python merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --title "生活向" --tid 160 --tag "生活,日常"
# 无 Cookie 时扫码登录，Cookie 保存到 push/bilibili/cookie.json
python merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --push-login --title "标题"

# 合并后通过 Playwright 浏览器上传 B 站（需在 playwright_push 中配置 Cookie）
python3 merge_mp4_ffmpeg2.py mapbinlist.txt --push playwright_bilibili --title "我的视频"
```

### 3.2 B 站登录方式

- **API 投稿（`--push bilibili`）**：在 `push/bilibili/cookie.json` 放置 JSON（`SESSDATA`、`bili_jct`、`DedeUserID`），或通过 `--push-cookie` 指定路径；可使用 `--push-login` 扫码登录。
- **Playwright 投稿（`--push playwright_bilibili`）**：在 `playwright_push/upload_bilibili.py` 中配置 `COOKIES_LIST` 或 `COOKIE_FILE`，合并完成后会调用该脚本上传。详见 `playwright_push/README.md`。

详见 `push/README.md`、`push/bilibili/README.md`、`playwright_push/README.md`。

---

## 文件一览

| 文件 | 作用 | 依赖 |
|------|------|------|
| `first_frame_ffmpeg.py` | 截第一帧（ffmpeg） | 系统 ffmpeg，URL 时 requests |
| `first_frame_moviepy.py` | 截第一帧（MoviePy） | moviepy、requests、ffmpeg |
| `merge_mp4_ffmpeg.py` | 列表合并，-c copy 不重编码 | 系统 ffmpeg |
| `merge_mp4_ffmpeg2.py` | 列表合并工程化版：支持列表 URL、tmp 按次目录、自动清临时 | 系统 ffmpeg，URL 时 requests |
| `merge_mp4_moviepy.py` | 列表合并，重编码压缩 | moviepy、requests、ffmpeg |
| `mapbinlist.txt` | 合并用列表示例 | - |
| `tmp/` | 截第一帧/合并的临时与默认输出；ffmpeg2 为 `tmp/merge_YYYYMMDD_HHMMSS/` | 自动创建 |
| `push/` | 推送模块：B 站等平台登录与投稿，可选、可扩展 | requests |

---

## 说明

- 截第一帧：URL 会先下载到临时文件（ffmpeg 版在 `tmp/`），截帧后删除临时视频；ffmpeg 版未指定 `-o` 时输出到 `tmp/<base>_first_frame.<ext>`。
- 合并：列表内可写本地路径或 HTTP(S) URL。**merge_mp4_ffmpeg2** 支持列表本身为本地文件或公网 URL，每次运行在 `tmp/merge_YYYYMMDD_HHMMSS/` 下下载分片、合并，默认输出文件按列表内容 MD5 命名（同列表同文件名、不同列表不同文件名），结束后只删分片与中间文件，保留合并结果。MoviePy 版会先下载 URL 到临时目录再合并，合并后删除临时文件。
- **推送**：使用 `--push bilibili`（API 投稿）或 `--push playwright_bilibili`（Playwright 浏览器投稿）可在合并后直接投稿 B 站；API 需配置 Cookie 或 `--push-login` 扫码，Playwright 需在 `playwright_push/` 中配置 Cookie。推送模块在 `push/`、`playwright_push/` 下，可扩展其他平台。

---

## 免责声明

**本仓库仅供学习与个人使用。** 使用本工具进行视频合并、上传等操作时，请遵守各平台（如 B 站）的服务条款与相关法律法规；因使用本工具产生的账号风险、内容纠纷或其它后果由使用者自行承担，作者不承担任何责任。请勿将本工具用于任何违法违规或违反平台规则之用途。
