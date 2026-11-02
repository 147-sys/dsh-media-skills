#!/usr/bin/env python3
"""Generate videos via Agnes AI (OpenAI Videos 兼容的异步接口)。

流程:
1. POST {base}/videos 创建任务,拿 video_id;
2. 轮询 GET {host}/agnesapi?video_id=...&model_name=... 直到 completed / failed;
3. 下载 url 到输出路径。

模式:
- text      纯文本生成视频
- keyframe  用首帧/尾帧约束(--first-frame / --last-frame,至少一个)
- reference 用参考图/音频/视频(--image / --audio / --video)

Key 从环境变量或 ~/.dsh/secrets/media-tools.env 读取,脚本不内置任何密钥。
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _force_utf8_output():
    """DSH 按 UTF-8 读取子进程输出,而 Windows 控制台默认 cp936,不转会导致中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_force_utf8_output()

DEFAULT_BASE = "https://apihub.agnes-ai.com/v1"
DEFAULT_MODEL = "agnes-video-2.5-flash"
FLASH_MAX_IMAGES = 5
FLASH_MAX_AUDIOS = 3

SECRET_FILES = (
    Path.home() / ".dsh/secrets/media-tools.env",
    Path.home() / ".codex/secrets/media-tools.env",
)


def get_key(name):
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for env_file in SECRET_FILES:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_key(name, hint):
    key = get_key(name)
    if not key:
        sys.exit(f"缺少 {name}:{hint}")
    return key


def base_url():
    return (get_key("AGNES_BASE_URL") or DEFAULT_BASE).rstrip("/")


def query_host():
    base = base_url()
    return base[:-3] if base.endswith("/v1") else base


def request_json(method, url, key, body=None, timeout=120):
    data = None
    headers = {"Authorization": "Bearer " + key}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:400]}
    except OSError as exc:
        return None, {"raw": f"{type(exc).__name__}: {exc}"}


def resolve_media(value):
    """公网 URL / data URI 原样返回;本地文件转成 data URI(官方更推荐公网 URL)。"""
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        sys.exit(f"媒体文件不存在:{value}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def create_task(body, key, queue_retries, quiet):
    url = base_url() + "/videos"
    delay = 15
    for attempt in range(queue_retries + 1):
        status, payload = request_json("POST", url, key, body=body, timeout=180)
        if status == 200 and isinstance(payload, dict):
            return payload
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        retryable = status in (None, 429, 500, 502, 503, 504) or code in ("video_queue_full",)
        if retryable and attempt < queue_retries:
            if not quiet:
                print(f"  队列繁忙({status} {code or message}),{delay}s 后重试 "
                      f"[{attempt + 1}/{queue_retries}]", flush=True)
            time.sleep(delay)
            delay = min(int(delay * 1.6), 90)
            continue
        sys.exit(f"创建视频任务失败 HTTP {status}:{json.dumps(payload, ensure_ascii=False)[:400]}")
    sys.exit("创建视频任务失败:队列持续繁忙。请稍后重试,或改用付费档 --model agnes-video-2.5"
             "(720P ¥0.15/秒),或提高 --queue-retries。")


def poll_task(video_id, key, model, timeout, interval, quiet):
    url = (f"{query_host()}/agnesapi?video_id={urllib.parse.quote(video_id)}"
           f"&model_name={urllib.parse.quote(model)}")
    deadline = time.time() + timeout
    shown = None
    backoff = interval
    while time.time() < deadline:
        status, payload = request_json("GET", url, key, timeout=60)
        if status != 200 or not isinstance(payload, dict):
            if not quiet:
                print(f"  查询异常 HTTP {status},重试中", flush=True)
            time.sleep(min(backoff * 2, 30))
            backoff = min(backoff * 2, 30)
            continue
        backoff = interval
        state = payload.get("status")
        progress = payload.get("progress")
        if (state, progress) != shown:
            if not quiet:
                print(f"  status={state} progress={progress}", flush=True)
            shown = (state, progress)
        if state == "completed":
            return payload
        if state == "failed":
            error = payload.get("error") or {}
            sys.exit(f"视频生成失败:{error.get('message') or json.dumps(payload, ensure_ascii=False)[:300]}")
        time.sleep(interval)
    sys.exit(f"等待超时({timeout}s):video_id={video_id},可稍后用该 id 重新查询")


def download(url, out):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-media-tools/1.0"})
    with urllib.request.urlopen(req, timeout=900) as resp, open(out, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)


def main():
    parser = argparse.ArgumentParser(description="用 Agnes AI 生成视频")
    parser.add_argument("prompt")
    parser.add_argument("out", nargs="?", default=None,
                        help="输出视频路径(缺省只返回 URL,不下载)")
    parser.add_argument("--model", default=None, help=f"默认 {DEFAULT_MODEL}")
    parser.add_argument("--mode", choices=["text", "keyframe", "reference"], default=None)
    parser.add_argument("--seconds", default="5", help='时长字符串 "4"-"12",默认 5')
    parser.add_argument("--size", default=None, help="720P / 1080P / 1K / 2K;flash 仅支持 720P")
    parser.add_argument("--ratio", default="16:9", help="21:9 16:9 4:3 1:1 3:4 9:16")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--first-frame", default=None)
    parser.add_argument("--last-frame", default=None)
    parser.add_argument("--image", action="append", default=[], help="reference 模式参考图(可重复)")
    parser.add_argument("--audio", action="append", default=[], help="reference 模式参考音频(可重复)")
    parser.add_argument("--video", action="append", default=[], help="reference 模式参考视频(可重复)")
    parser.add_argument("--timeout", type=int, default=1800, help="轮询总超时秒数,默认 1800")
    parser.add_argument("--poll", type=float, default=3.0, help="轮询间隔秒数,默认 3")
    parser.add_argument("--queue-retries", type=int, default=6, help="队列繁忙重试次数")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    key = load_key("AGNES_API_KEY", "请在 ~/.dsh/secrets/media-tools.env 或环境变量中配置")
    model = args.model or get_key("AGNES_VIDEO_MODEL") or DEFAULT_MODEL
    is_flash = model.endswith("flash")

    mode = args.mode
    if not mode:
        if args.first_frame or args.last_frame:
            mode = "keyframe"
        elif args.image or args.audio or args.video:
            mode = "reference"
        else:
            mode = "text"

    size = args.size or "720P"
    if is_flash and size != "720P":
        sys.exit('agnes-video-2.5-flash 仅支持 size="720P"')

    try:
        seconds = int(str(args.seconds))
    except ValueError:
        sys.exit("--seconds 必须是 4-12 的整数")
    if not 4 <= seconds <= 12:
        sys.exit("--seconds 必须在 4-12 之间")

    body = {"model": model, "prompt": args.prompt, "mode": mode,
            "seconds": str(seconds), "size": size, "aspect_ratio": args.ratio}
    if args.seed is not None:
        body["seed"] = args.seed

    if mode == "keyframe":
        if not (args.first_frame or args.last_frame):
            sys.exit("keyframe 模式需要 --first-frame 和/或 --last-frame")
        if args.first_frame:
            body["first_frame"] = resolve_media(args.first_frame)
        if args.last_frame:
            body["last_frame"] = resolve_media(args.last_frame)
    elif mode == "reference":
        if not (args.image or args.audio or args.video):
            sys.exit("reference 模式至少要有一类参考素材(--image/--audio/--video)")
        if args.image:
            if is_flash and len(args.image) > FLASH_MAX_IMAGES:
                sys.exit(f"agnes-video-2.5-flash 参考图最多 {FLASH_MAX_IMAGES} 张")
            body["images"] = [resolve_media(item) for item in args.image]
        if args.audio:
            if is_flash and len(args.audio) > FLASH_MAX_AUDIOS:
                sys.exit(f"agnes-video-2.5-flash 参考音频最多 {FLASH_MAX_AUDIOS} 段")
            body["audios"] = [resolve_media(item) for item in args.audio]
        if args.video:
            if is_flash:
                sys.exit("agnes-video-2.5-flash 不支持参考视频,请改用 agnes-video-2.5")
            body["videos"] = [{"url": resolve_media(item)} for item in args.video]

    if not args.quiet:
        print(f"创建任务: model={model} mode={mode} size={size} ratio={args.ratio} {seconds}s")

    created = create_task(body, key, args.queue_retries, args.quiet)
    video_id = created.get("video_id") or created.get("id")
    if not video_id:
        sys.exit(f"响应缺少 video_id:{json.dumps(created, ensure_ascii=False)[:300]}")
    if not args.quiet:
        print(f"video_id={video_id} status={created.get('status')}")

    result = poll_task(video_id, key, model, args.timeout, args.poll, args.quiet)
    url = result.get("url")
    if not url:
        sys.exit(f"任务完成但响应没有 url:{json.dumps(result, ensure_ascii=False)[:300]}")

    print(f"url: {url}")
    print(f"video_id: {video_id}")
    if args.out:
        download(url, args.out)
        print(f"done: {args.out}  [{model} {size} {result.get('seconds')}s]")


if __name__ == "__main__":
    main()
