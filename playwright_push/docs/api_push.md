# B 站投稿 POST 接口文档（api_push）

将多段 mp4 合并为一个视频并推送到 B 站，返回审核状态或错误信息。

## 基本信息

| 项目 | 说明 |
|------|------|
| 路径 | `/push/playwright_bilibili` |
| 方法 | `POST` |
| Content-Type | `application/json` |
| 默认端口 | `8188` |

## 启动服务

```bash
# 项目根目录
python3 -m playwright_push.api_push --host 0.0.0.0 --port 8188

# 或
flask --app playwright_push.api_push run --host 0.0.0.0 --port 8188
```

## 请求体（JSON）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `videos` | 数组（字符串） | 是 | mp4 本地路径或 URL 数组，顺序即合成顺序 |
| `gindex` | 整数 | 否 | 业务索引，原样写入日志与返回 |
| `guid` | 字符串 | 否 | 业务标识，原样写入日志与返回 |
| `version` | 字符串/整数 | 否 | 版本号，原样写入日志与返回 |
| `retry` | 整数 | 否 | 推送失败重试次数，默认 1（即不重试） |
| `reencode` | 布尔 | 否 | 合并后是否重编码，默认 false（仅 remux 修时间戳） |
| `title` | 字符串 | 否 | 投稿标题，不传则用合并后文件名（不含扩展名） |

## 响应结构

所有响应 HTTP 状态码均为 `200`，业务结果由 body 中的 `code` 区分。

### 通用字段

- `code`: 整数，业务码（见下表）
- `data`: 数组，固定一项对象；`code=-100` 时为 `null`
- `msg`: 字符串，仅 `code=-100` 时存在，为错误说明

### data 项字段（code=0 或 code=-200 时）

| 字段 | 类型 | 说明 |
|------|------|------|
| `audit_status` | 字符串 | 审核状态：`passed` 已通过、`rejected` 未通过、`error` 等 |
| `DedeUserID` | 字符串 | 使用的 B 站账号 DedeUserID |
| `video_name` | 字符串 | 合并后的视频文件名 |
| `error_reason` | 字符串 | 失败原因，成功或已通过时为空字符串 |
| `duration_sec` | 数值 | 本次请求总耗时（秒） |
| `gindex` | - | 请求中的 gindex |
| `guid` | 字符串 | 请求中的 guid |
| `version` | - | 请求中的 version |

## 业务码说明

| code | 含义 | data | 说明 |
|------|------|------|------|
| **0** | 成功（有明确审核结果） | 数组一项 | 仅当审核状态为 **已通过**（`passed`）或 **未通过**（`rejected`）。由 `data[0].audit_status` 区分；`error_reason` 在未通过时才有内容。 |
| **-100** | 视频合并前/合并失败 | `null` | 参数错误（如缺少/无效 `videos`、无效 JSON）或合并过程异常（如 404、ffmpeg 失败）。详见 `msg`。 |
| **-200** | 其余失败 | 数组一项 | Cookie 未配置/过期、push 到 B 站失败、投稿未进「进行中」、审核超时等。失败原因在 `data[0].error_reason`。 |

## 审核状态约定

- **code=0** 时，`audit_status` 仅可能为：
  - `passed`：已通过
  - `rejected`：未通过
- 其余情况（未提交成功、超时、Cookie 错误、push 异常等）一律 **code=-200**，通过 `error_reason` 表示原因，不通过 `audit_status` 表示“错误类型”。

## 请求示例

```bash
curl -X POST http://127.0.0.1:8188/push/playwright_bilibili \
  -H "Content-Type: application/json" \
  -d '{
    "videos": ["/path/to/a.mp4", "http://cdn.example.com/b.mp4"],
    "gindex": 1,
    "guid": "task-001",
    "version": 1,
    "retry": 2,
    "reencode": false,
    "title": "我的投稿标题"
  }'
```

最小请求（仅必填）：

```json
{
  "videos": ["/path/to/video.mp4"]
}
```

## 响应示例

### code=0，审核已通过

```json
{
  "code": 0,
  "data": [{
    "audit_status": "passed",
    "DedeUserID": "412653959",
    "video_name": "merged_xxx.mp4",
    "error_reason": "",
    "duration_sec": 120.5,
    "gindex": 1,
    "guid": "task-001",
    "version": 1
  }]
}
```

### code=0，审核未通过

```json
{
  "code": 0,
  "data": [{
    "audit_status": "rejected",
    "DedeUserID": "412653959",
    "video_name": "merged_xxx.mp4",
    "error_reason": "审核未通过/已退回，请到创作中心查看原因",
    "duration_sec": 95.2,
    "gindex": 1,
    "guid": "task-001",
    "version": 1
  }]
}
```

### code=-100，参数/合并错误

```json
{
  "code": -100,
  "data": null,
  "msg": "缺少参数 videos（mp4 路径或 URL 数组）"
}
```

### code=-200，Cookie 或 push 失败

```json
{
  "code": -200,
  "data": [{
    "audit_status": "error",
    "DedeUserID": "",
    "video_name": "merged_xxx.mp4",
    "error_reason": "未配置 Cookie。请填写 COOKIES_LIST（数组）或 COOKIE_FILE / COOKIES_DICT。",
    "duration_sec": 32.1,
    "gindex": 1,
    "guid": "task-001",
    "version": 1
  }]
}
```

## Cookie 配置

- 接口使用 **与 api_push 同目录** 的 `cookie.json`（即 `playwright_push/cookie.json`）。
- 格式：单账号为对象 `{"SESSDATA":"...","bili_jct":"...","DedeUserID":"..."}`，多账号为数组 `[{...}, {...}]`。
- 多账号时脚本会**随机选一个**先试，不可用再试其他。

## 流程简述

1. 校验 `videos`，合并为单个 mp4（merge_mp4_ffmpeg2 逻辑）。
2. 使用 `playwright_push/cookie.json` 中的 Cookie，随机顺序尝试账号。
3. 打开 B 站创作中心上传页，上传合并后的视频，填标题，设置可见范围，投稿。
4. 校验「投稿中」列表是否出现「进行中」，未出现则重试投稿或换账号。
5. 可选轮询审核结果（已通过/未通过），或超时/异常则按失败处理。
6. 仅当得到 **已通过** 或 **未通过** 时返回 `code=0`，其余失败均返回 `code=-200`。
