#!/usr/bin/env python3
"""Generate images via Agnes AI, SenseNova U1 Fast, or SiliconFlow Kolors.

Provider selection order:
1. --provider agnes|sensenova|siliconflow
2. MEDIA_IMAGE_PROVIDER environment variable
3. First provider that has a key configured: Agnes -> SenseNova -> SiliconFlow

Keys are read from the process environment, then from
~/.dsh/secrets/media-tools.env, then ~/.codex/secrets/media-tools.env.
No key is bundled with this script.
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

SILICONFLOW_URL = "https://api.siliconflow.cn/v1/images/generations"
SILICONFLOW_MODEL = "Kwai-Kolors/Kolors"
SENSENOVA_URL = "https://token.sensenova.ai/v1/images/generations"
SENSENOVA_MODEL = "sensenova-u1-fast"

# Agnes AI(国际站).中国站为 https://api.agnes-ai.cn/v1,但同一把 key 不一定两边都有效。
AGNES_DEFAULT_BASE = "https://apihub.agnes-ai.com/v1"
AGNES_IMAGE_MODEL = "agnes-image-2.5-flash"

# SenseNova U1 Fast supported sizes (WxH -> aspect ratio).
SENSENOVA_SIZES = {
    "1344x3136": (9, 21),
    "1536x2752": (9, 16),
    "1664x2496": (2, 3),
    "1760x2368": (3, 4),
    "1824x2272": (4, 5),
    "2048x2048": (1, 1),
    "2272x1824": (5, 4),
    "2368x1760": (4, 3),
    "2496x1664": (3, 2),
    "2752x1536": (16, 9),
    "3072x1376": (21, 9),
}

# Agnes Image supported size tiers and aspect ratios.
AGNES_TIERS = ("1K", "2K", "3K", "4K")
AGNES_RATIOS = ("1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9")

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


def load_key(name):
    key = get_key(name)
    if not key:
        sys.exit(
            f"缺少 {name}:请设置环境变量,或在 ~/.dsh/secrets/media-tools.env 中配置(每行 KEY=value)"
        )
    return key


def agnes_base():
    return (get_key("AGNES_BASE_URL") or AGNES_DEFAULT_BASE).rstrip("/")


def http_post_json(url, body, key, timeout=300, retries=3):
    """POST JSON with backoff on 429/5xx. Returns the decoded JSON payload."""
    payload = json.dumps(body).encode()
    last_error = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last_error = f"HTTP {exc.code}: {detail}"
            if exc.code in (408, 409, 425, 429) or exc.code >= 500:
                time.sleep(min(2 ** attempt * 3, 45))
                continue
            sys.exit(f"请求失败 {last_error}")
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** attempt * 3, 45))
    sys.exit(f"请求多次重试后仍失败 {last_error}")


def download(url, out):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-media-tools/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)


def sensenova_size(size):
    """Map a user-supplied size to one of SenseNova's supported sizes."""
    size = (size or "2048x2048").strip().lower()
    if size in SENSENOVA_SIZES:
        return size
    if ":" in size:
        try:
            wr, hr = map(int, size.split(":"))
            for cand, (cw, ch) in SENSENOVA_SIZES.items():
                if cw == wr and ch == hr:
                    return cand
        except ValueError:
            pass
    try:
        w, h = map(int, size.split("x"))
        target = w / h
        best = min(SENSENOVA_SIZES.items(), key=lambda kv: abs((kv[1][0] / kv[1][1]) - target))
        return best[0]
    except (ValueError, ZeroDivisionError):
        return "2048x2048"


def _nearest_ratio(target):
    best, best_delta = "1:1", None
    for ratio in AGNES_RATIOS:
        wr, hr = map(int, ratio.split(":"))
        delta = abs(wr / hr - target)
        if best_delta is None or delta < best_delta:
            best, best_delta = ratio, delta
    return best


def agnes_size(size):
    """Map a user-supplied size to Agnes (size tier, aspect ratio)."""
    raw = (size or "1K").strip()
    upper = raw.upper()

    if upper in AGNES_TIERS:
        return upper, "1:1"
    if raw in AGNES_RATIOS:
        return "1K", raw
    if ":" in raw:
        try:
            wr, hr = map(int, raw.split(":"))
            if wr > 0 and hr > 0:
                return "1K", _nearest_ratio(wr / hr)
        except ValueError:
            pass
    try:
        w, h = map(int, raw.lower().split("x"))
        longest = max(w, h)
        tier = "4K" if longest > 3200 else "3K" if longest > 2200 else "2K" if longest > 1400 else "1K"
        return tier, _nearest_ratio(w / h)
    except (ValueError, ZeroDivisionError):
        return "1K", "1:1"


def to_data_uri(value):
    """Accept an http(s)/data URI, or read a local file into a data URI."""
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        sys.exit(f"参考图不存在:{value}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def generate_agnes(prompt, out, size, key, model, images, want_base64):
    tier, ratio = agnes_size(size)
    body = {"model": model, "prompt": prompt, "size": tier, "ratio": ratio}
    extra = {}
    if images:
        # 图生图/多图合成:按官方 FAQ,输入图放在 extra_body.image。
        extra["image"] = [to_data_uri(item) for item in images]
    if want_base64:
        extra["response_format"] = "b64_json"
    elif images:
        extra["response_format"] = "url"
    if extra:
        body["extra_body"] = extra

    data = http_post_json(agnes_base() + "/images/generations", body, key)
    if data.get("error"):
        sys.exit(f"Agnes 返回错误:{json.dumps(data['error'], ensure_ascii=False)[:400]}")
    items = data.get("data") or []
    if not items:
        sys.exit(f"Agnes 响应缺少 data 字段:{json.dumps(data, ensure_ascii=False)[:400]}")
    item = items[0]
    if item.get("b64_json"):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        download(item["url"], out)
    else:
        sys.exit(f"Agnes 响应既无 url 也无 b64_json:{json.dumps(item, ensure_ascii=False)[:300]}")
    print(f"done: {out}  [agnes {model} {tier} {ratio}]")


def generate_sensenova(prompt, out, size, key):
    body = {"model": SENSENOVA_MODEL, "prompt": prompt, "size": sensenova_size(size), "n": 1}
    data = http_post_json(SENSENOVA_URL, body, key)
    download(data["data"][0]["url"], out)
    print(f"done: {out}  [sensenova {SENSENOVA_MODEL}]")


def generate_siliconflow(prompt, out, size, key):
    body = {"model": SILICONFLOW_MODEL, "prompt": prompt, "image_size": size, "batch_size": 1}
    data = http_post_json(SILICONFLOW_URL, body, key)
    download(data["images"][0]["url"], out)
    print(f"done: {out}  [siliconflow {SILICONFLOW_MODEL}]")


def pick_provider(explicit):
    if explicit:
        return explicit
    env = (os.environ.get("MEDIA_IMAGE_PROVIDER") or "").strip().lower()
    if env:
        return env
    for name, var in (("agnes", "AGNES_API_KEY"),
                      ("sensenova", "SENSENOVA_API_KEY"),
                      ("siliconflow", "SILICONFLOW_API_KEY")):
        if get_key(var):
            return name
    return None


def main():
    parser = argparse.ArgumentParser(description="生成图片(Agnes / SenseNova / SiliconFlow)")
    parser.add_argument("prompt", help="提示词")
    parser.add_argument("out", help="输出图片路径")
    parser.add_argument("size", nargs="?", default=None,
                        help="尺寸:Agnes 用 1K/2K/3K/4K 档位 + 比例,或直接给 16:9 / 1024x1024")
    parser.add_argument("--provider", choices=["agnes", "sensenova", "siliconflow"], default=None)
    parser.add_argument("--image", action="append", default=[],
                        help="参考图(Agnes 图生图/多图合成,可重复)")
    parser.add_argument("--base64", action="store_true", help="要求服务端返回 base64(Agnes)")
    parser.add_argument("--model", default=None, help="覆盖模型名")
    args = parser.parse_args()

    provider = pick_provider(args.provider)
    if not provider:
        sys.exit(
            "缺少图片生成 Key:请配置 AGNES_API_KEY / SENSENOVA_API_KEY / SILICONFLOW_API_KEY"
            "(环境变量或 ~/.dsh/secrets/media-tools.env)"
        )

    if provider == "agnes":
        size = args.size or "1K"
        generate_agnes(prompt=args.prompt, out=args.out, size=size,
                       key=load_key("AGNES_API_KEY"),
                       model=args.model or get_key("AGNES_IMAGE_MODEL") or AGNES_IMAGE_MODEL,
                       images=args.image, want_base64=args.base64)
    elif provider == "sensenova":
        generate_sensenova(args.prompt, args.out, args.size or "1024x1024", load_key("SENSENOVA_API_KEY"))
    else:
        generate_siliconflow(args.prompt, args.out, args.size or "1024x1024", load_key("SILICONFLOW_API_KEY"))


if __name__ == "__main__":
    main()
