---
name: media-tools
description: "图片与视频生成。用户要求生成图片、插画、头像、封面、背景、banner、海报或其他视觉素材，或要求文生视频、图生视频、短视频素材时使用。图片默认优先 Agnes AI（agnes-image-2.5-flash），其次 SenseNova U1 Fast，再次 SiliconFlow Kolors；视频使用 Agnes（agnes-video-2.5-flash / agnes-video-2.5）。密钥只从环境变量或 ~/.dsh/secrets/media-tools.env、~/.codex/secrets/media-tools.env 读取，不内置、不写入任何密钥。"
---

# Media Tools（图片 + 视频生成）

通过用户自行配置的服务商生成图片和视频素材。

- **图片**：已配置 `AGNES_API_KEY` 时优先 Agnes AI（`agnes-image-2.5-flash`）；否则 SenseNova U1 Fast；否则 SiliconFlow Kolors。
- **视频**：Agnes AI，`agnes-video-2.5-flash`（免费档、仅 720P）或 `agnes-video-2.5`（720P/1080P/1K/2K）。

## 用法

图片：

```bash
python3 scripts/generate.py "<提示词>" <输出路径.png> [尺寸]
python3 scripts/generate.py "<提示词>" <输出路径.png> [尺寸] --image <参考图> [--image ...]
```

示例：

```bash
python3 scripts/generate.py "云海中的中国宫殿，写实电影感，气势恢宏" palace.jpg 16:9
python3 scripts/generate.py "简洁科技感产品发布会背景，深蓝渐变" banner.png 2752x1536
python3 scripts/generate.py "改成赛博朋克风格，保留原构图" out.png 2K --image input.png
```

视频（异步任务，自动轮询并下载）：

```bash
python3 scripts/generate_video.py "<提示词>" <输出路径.mp4> [--seconds 5] [--size 720P] [--ratio 16:9]
```

示例：

```bash
# 文生视频
python3 scripts/generate_video.py "雨后的未来城市街道，霓虹灯倒映地面，银色跑车缓慢驶过，电影级运镜" street.mp4 --seconds 5

# 首尾帧控制
python3 scripts/generate_video.py "人物自然转身走向窗边，镜头缓慢推进" move.mp4 --mode keyframe --first-frame a.png --last-frame b.png

# 参考图生成（<Picture 1> 指代第一张参考图）
python3 scripts/generate_video.py "以 <Picture 1> 的角色为参考，在花田中奔跑，低机位跟拍" run.mp4 --mode reference --image character.png
```

视频脚本常用参数：

| 参数 | 说明 |
| - | - |
| `--mode` | `text` / `keyframe` / `reference`；不传则按所给素材自动推断 |
| `--seconds` | 字符串 `"4"`–`"12"`，默认 5 |
| `--size` | `720P` / `1080P` / `1K` / `2K`；`agnes-video-2.5-flash` 只接受 `720P` |
| `--ratio` | `21:9` `16:9` `4:3` `1:1` `3:4` `9:16`，默认 `16:9` |
| `--first-frame` / `--last-frame` | keyframe 模式的首帧/尾帧（公网 URL 或本地文件） |
| `--image` / `--audio` / `--video` | reference 模式参考素材；flash 最多 5 图 3 音频且不支持参考视频 |
| `--seed` / `--timeout` / `--poll` / `--queue-retries` | 复现性、轮询总超时、轮询间隔、队列繁忙重试 |

视频接口是异步的：先 `POST /v1/videos` 拿 `video_id`，再轮询 `GET /agnesapi?video_id=...&model_name=...`。脚本已内置 503 `video_queue_full` 退避重试、429/5xx 重试和完成后自动下载。

## 尺寸

- **Agnes 图片**：用 `size` 档位（`1K`/`2K`/`3K`/`4K`）配合 `ratio`（`1:1` `3:4` `4:3` `16:9` `9:16` `2:3` `3:2` `21:9`）。脚本也接受 `16:9`、`1024x1024` 这类写法，会映射到最接近的档位与比例。
- **Agnes 视频**：`size` 只选分辨率档位，画幅用 `--ratio`，不能传 `1280x720` 这类像素尺寸。
- **SenseNova**：支持常见横竖方比例，也可传精确尺寸，脚本映射到最接近的支持尺寸。
- **SiliconFlow**：第三参数作为 `image_size` 传给 Kolors。
- 缺省尺寸：图片 `1K`（Agnes）/ `1024x1024`（其他），视频 `720P` + `16:9`。

## 密钥来源

按顺序读取：

1. 进程环境变量；
2. `~/.dsh/secrets/media-tools.env`；
3. `~/.codex/secrets/media-tools.env`（历史兼容）。

支持的 key：

- `AGNES_API_KEY`：图片（`agnes-image-2.5-flash`）与视频（`agnes-video-2.5-flash` / `agnes-video-2.5`）。
- `AGNES_BASE_URL`：可选，默认 `https://apihub.agnes-ai.com/v1`。**国际站与中国站密钥不通用**，中国站签发请改用 `https://api.agnes-ai.cn/v1`。
- `AGNES_IMAGE_MODEL` / `AGNES_VIDEO_MODEL`：可选，覆盖默认模型。
- `SENSENOVA_API_KEY`：Agnes 未配置时的图片服务商。
- `SILICONFLOW_API_KEY`：最后兜底的图片服务商。
- `MEDIA_IMAGE_PROVIDER`：可选，强制指定 `agnes` / `sensenova` / `siliconflow`。

Secrets 文件每行一个 `KEY=value`，建议限制为当前用户可读。本技能不读取或修改 DSH 模型配置，也不内置任何 key。

## 计费提示

- Agnes 图片当前为 `¥0`（各档位均免费）。
- `agnes-video-2.5-flash` 当前限时免费（仅 720P，最多 5 图 / 3 音频）。
- `agnes-video-2.5` 按秒计费：720P `¥0.15/s`，1080P 与 1K `¥0.25/s`，2K `¥0.35/s`。
- 生成前请确认额度；批量或长视频任务优先用 flash 档。

## 输出和隐私

- 生成文件只写到命令指定的输出路径。
- 不要自动上传、复制到公开目录或提交到仓库。
- 提示词中不要包含证件号、客户资料、未公开商业信息等敏感内容，除非用户明确授权并确认服务商合规。
- 避免在未授权情况下要求复现可识别个人、私有参考图或许可受限的角色/品牌素材。
- 参考素材必须是服务商可公网访问的 URL；本地文件会被转成 data URI，但**公网 URL 更稳定**。

## 故障排查

- 提示缺少 key：在环境变量或 `~/.dsh/secrets/media-tools.env` 中配置对应 key。
- `401 无效的密钥`：多为站点不匹配——国际站 key 用 `apihub.agnes-ai.com`，中国站 key 用 `api.agnes-ai.cn`；也可能 key 已失效，需在控制台重建。
- `503 video_queue_full`：视频队列繁忙，脚本会自动退避重试；仍失败请稍后再试。
- `400 size must be 720P`：flash 模型不支持其他分辨率，改用 `--model agnes-video-2.5` 或改回 `720P`。
- 视频任务超时：用打印出的 `video_id` 直接重新查询，任务通常仍在后台继续。
