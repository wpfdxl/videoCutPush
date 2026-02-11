# cut_video_first_frame

MP4 小工具：**截取第一帧**（ffmpeg / MoviePy。

## 环境

- Python 3.6+
- 系统安装 ffmpeg（所有脚本都依赖）

```bash
# macOS
brew install ffmpeg
```

## 安装依赖

仅 **截第一帧 MoviePy 版** 和 **合并 MoviePy 版** 需要安装 Python 依赖；ffmpeg 版只需系统 ffmpeg（远程 URL 时可选 `requests`）。

```bash
cd /path/to/video_deal_test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 含：`moviepy`、`requests`。

---

## 一、截取第一帧

### 1.1 高效版：first_frame_ffmpeg.py（推荐）

直接调系统 ffmpeg，只解一帧，不把整段视频载入 Python。**临时文件与未指定 `-o` 时的输出均在项目 `tmp/` 目录。**

- **依赖**：系统 ffmpeg；处理 URL 时需 `pip install requests`。

```bash
# 本地文件（无需 requests）
python first_frame_ffmpeg.py /path/to/video.mp4

# 不指定 -o 时，输出到 tmp/<base>_first_frame.png
python first_frame_ffmpeg.py "https://cdn.example.com/path/video.mp4"

# 指定输出路径和格式
python first_frame_ffmpeg.py /path/to/video.mp4 -o cover.jpg -f jpg
python first_frame_ffmpeg.py "https://cdn.example.com/video.mp4" -o /tmp/out.png --ffmpeg /usr/local/bin/ffmpeg
```

| 参数 | 说明 |
|------|------|
| `source` | 视频 URL 或本地文件路径 |
| `-o, --output` | 输出图片路径（不传则写入 `tmp/<base>_first_frame.png`） |
| `-f, --format` | 图片格式：png、jpg（默认 png） |
| `--ffmpeg` | ffmpeg 可执行路径（默认 `ffmpeg`） |

```python
from first_frame_ffmpeg import capture_first_frame

out = capture_first_frame("https://cdn.example.com/video.mp4")           # 输出到 tmp/
out = capture_first_frame("/path/to/video.mp4", output_path="cover.png", format="jpg")
```

### 1.2 MoviePy 版：first_frame_moviepy.py

使用 MoviePy（内部 imageio-ffmpeg）。需安装 `moviepy`、`requests`。未指定 `-o` 时输出到当前工作目录。

```bash
python first_frame_moviepy.py "https://your-bucket.oss.aliyuncs.com/path/video.mp4"
python first_frame_moviepy.py /path/to/local.mp4 -o frame.png -f jpg
```

| 参数 | 说明 |
|------|------|
| `source` | 视频 URL 或本地文件路径 |
| `-o, --output` | 输出图片路径（不传则自动生成到当前目录） |
| `-f, --format` | 图片格式（默认 png） |

```python
from first_frame_moviepy import capture_first_frame

out = capture_first_frame("https://cdn.example.com/video.mp4")
out = capture_first_frame("/path/to/video.mp4", output_path="cover.png", format="jpg")
```

---