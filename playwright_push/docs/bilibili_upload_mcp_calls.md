# B 站视频上传并发布 - Playwright MCP 调用过程列表

**视频文件**：`/Users/xxx/Downloads/4444.mp4`  
**目标**：在已打开的浏览器中重新上传该视频并发布。

---

## 调用过程列表（按执行顺序）

| 序号 | MCP 工具 | 参数 | 说明 |
|------|----------|------|------|
| 1 | **playwright_navigate** | `url`: `https://member.bilibili.com/platform/upload/video/frame`<br>`headless`: `false` | 打开 B 站创作中心「视频投稿」上传页（有头模式） |
| 2 | **playwright_evaluate** | `script`: 将页面中所有 `input[type=file]` 的样式改为可见（display:block, visibility:visible, position:fixed 等），以便后续 upload_file 能命中 | 因 B 站上传区文件选择框默认被隐藏，需先通过 JS 使其可见，否则 `playwright_upload_file` 会因「元素不可见」超时 |
| 3 | **playwright_upload_file** | `selector`: `input[type="file"]`<br>`filePath`: `/Users/hf/Downloads/4444.mp4` | 向第一个文件选择框上传本地视频，上传成功后页面会显示「上传完成」 |
| 4 | **playwright_get_visible_text** | `{}` | 获取当前页可见文案，确认视频已上传并进入基本设置（标题、分区、立即投稿等） |
| 5 | **playwright_fill** | `selector`: `input[placeholder*="标题"], .form-item input, textarea`<br>`value`: `4444` | 填写标题（若已有标题可保持或覆盖为「4444」） |
| 6 | **playwright_click** | `selector`: `text=立即投稿` | 点击「立即投稿」按钮，提交稿件 |
| 7 | **playwright_get_visible_text** | `{}` | 再次获取页面文案，确认是否进入「稿件处理进度」或成功/审核中状态 |

---

## 关键点说明

1. **为何要先 `playwright_evaluate`**  
   B 站上传页的 `input[type="file"]` 被设计为不可见（由「点击上传」区域遮挡）。Playwright MCP 的 `playwright_upload_file` 要求目标元素**可见**，因此需先用 `playwright_evaluate` 在页面里把 file input 设为可见，再执行上传。

2. **evaluate 脚本要点**  
   - 用 `document.querySelectorAll('input[type=file]')` 找到所有文件输入框。  
   - 对每个设置：`display:block`、`visibility:visible`、`opacity:1`、`position:fixed`、位置与尺寸、`z-index:999999`，确保被 MCP 判定为可见。

3. **发布后**  
   点击「立即投稿」后，页面会进入稿件处理/审核流程；若出现「稿件处理进度」等文案，表示已提交，可在「投稿管理」中查看审核状态。

---

## 可复用的最小调用序列（仅上传+发布）

若已登录且当前页即为上传页，可只执行：

1. `playwright_evaluate`（使 file input 可见）  
2. `playwright_upload_file`（上传 `/Users/hf/Downloads/4444.mp4`）  
3. `playwright_fill`（填标题）  
4. `playwright_click`（点「立即投稿」）

如需从零打开页面，则在最前面加一步 `playwright_navigate` 到 `https://member.bilibili.com/platform/upload/video/frame`。
