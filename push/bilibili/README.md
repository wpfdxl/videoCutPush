# B 站推送 (bilibili)

参考 [](https://github.com//) 的登录与投稿流程，实现扫码登录、Cookie 文件登录与视频投稿。

## 功能特点

- **扫码登录自动获取 token**：扫码登录后自动获取 `access_token` 并保存为  格式，启用 APP 接口投稿（成功率更高）
- **智能错误处理**：自动检测 Cookie/Token 失效，提供友好的重新登录提示
- **完整上传流程**：preupload → 分片上传 → 提交稿件，协议与  完全对齐
- **多种登录方式**：扫码登录（推荐）、Cookie 文件导入

## 快速开始

### 1. 扫码登录（推荐）

```bash
python3 merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --push-login --title "你的标题"
```

扫码登录会：
- 生成二维码图片保存到 `push/tmp/bilibili_qrcode.png`
- 自动获取 `access_token` 并保存为  格式到 `push/bilibili/cookie.json`
- 后续上传自动使用 APP 接口投稿（成功率更高）

### 2. 使用  的 cookie 文件

如果你已经使用  登录过，可以直接复制其 `cookies.json`：

```bash
#  的 cookies.json 通常在其运行目录下
cp /path/to//cookies.json push/bilibili/cookie.json
```

### 3. Token 失效时重新登录

当提示 "access_token 已失效" 或 "Cookie 已失效" 时：

**方法1**: 删除旧 cookie 后重新扫码登录
```bash
rm push/bilibili/cookie.json
python3 merge_mp4_ffmpeg2.py mapbinlist.txt --push bilibili --push-login --title "标题"
```

**方法2**: 使用  重新登录
```bash
# 在  目录下
./ login
# 然后复制生成的 cookies.json
cp cookies.json /path/to/videoCutPush/push/bilibili/cookie.json
```

## Cookie 文件格式

支持三种格式：

### 1.  完整格式（推荐，含 token_info 用于 APP 投稿）

```json
{
  "cookie_info": {
    "cookies": [
      {"name": "SESSDATA", "value": "...", "expires": ...},
      {"name": "bili_jct", "value": "...", "expires": ...},
      {"name": "DedeUserID", "value": "...", "expires": ...}
    ],
    "domains": [".bilibili.com", ".biligame.com"]
  },
  "token_info": {
    "access_token": "...",
    "refresh_token": "...",
    "expires_in": 15552000,
    "mid": 123456789
  },
  "platform": "BiliTV"
}
```

有 `token_info.access_token` 时，自动使用 **APP 接口投稿**（成功率更高，与  一致）。

### 2. 简单 JSON 格式

```json
{
  "SESSDATA": "你的SESSDATA",
  "bili_jct": "你的bili_jct",
  "DedeUserID": "你的用户ID"
}
```

仅使用 Cookie 时，会使用 **Web 接口投稿**。

### 3. Cookie 字符串格式

```json
{
  "cookie": "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"
}
```

## 投稿参数

```bash
python3 merge_mp4_ffmpeg2.py mapbinlist.txt \
  --push bilibili \
  --title "标题（最多80字）" \
  --desc "简介" \
  --tag "标签1,标签2,标签3"
```

## 常见问题

### Q: 报错 "access_token 已失效"？
A: 按上面"Token 失效时重新登录"的方法重新登录即可。

### Q: 报错 21566 "投稿过于频繁"？
A: 这是 B 站的频率限制，等待 5-10 分钟后再试。

### Q: 为什么推荐使用扫码登录而不是手动复制 Cookie？
A: 扫码登录会自动获取 `access_token`，可以使用 APP 接口投稿，成功率比 Web 接口更高。
