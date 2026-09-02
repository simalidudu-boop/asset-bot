"""
media.py — $0 promo media pipeline.

Images:  1) Cloudflare Workers AI Flux Schnell (10k free neurons/day)
         2) Pollinations free Flux (no key — VERIFIED LIVE 2026-09-01)
Video:   slideshow = images + TTS narration + ffmpeg (runs on GitHub runner)
TTS:     Cloudflare Workers AI TTS (neuron budget) with silent-fallback
         (video without narration) if TTS unavailable.
"""
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT_DIR = Path(os.environ.get("MEDIA_OUT", "out/media"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- images
def _cf_image(prompt: str, size: str = "1024x1024") -> bytes:
    account = os.environ["CF_ACCOUNT_ID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    # Flux rejects overly long prompts with a bare HTTP 400 (observed 2026-09).
    payload = {"prompt": prompt[:1800]}  # NOTE: num_steps is rejected by CF
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (asset-bot)"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    if not data.get("success"):
        raise RuntimeError(f"cf image: {data.get('errors')}")
    # response is a base64 png inside result.image
    import base64
    return base64.b64decode(data["result"]["image"])


def _pollinations_image(prompt: str, size: str = "1024x1024") -> bytes:
    w, h = size.split("x")
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(prompt) + f"?width={w}&height={h}&model=flux&nologo=true")
    req = urllib.request.Request(url, headers={"User-Agent": "asset-bot/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def gen_image(prompt: str, slug: str, size: str = "1024x1024") -> Path:
    """Returns path to saved image; cascades CF -> Pollinations."""
    for name, fn in (("cf", _cf_image), ("pollinations", _pollinations_image)):
        try:
            data = fn(prompt, size)
            p = OUT_DIR / f"{slug}-{name}.jpg"
            p.write_bytes(data)
            return p
        except Exception as e:
            print(f"[media] {name} image failed: {e}")
            time.sleep(2)
    raise RuntimeError("all image providers failed")


# ---------------------------------------------------------------- tts
def _cf_tts(text: str) -> bytes | None:
    account = os.environ["CF_ACCOUNT_ID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/myshell-ai/melotts"
    payload = {"prompt": text[:400]}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    if not data.get("success") or not data.get("result"):
        return None
    import base64
    return base64.b64decode(data["result"].get("audio", "")) or None


# ---------------------------------------------------------------- video
def slideshow_video(image_paths: list[Path], narration: str,
                    out_name: str, duration_per: float = 3.0,
                    width: int = 1080, height: int = 1080) -> Path:
    """Stitch images + optional TTS narration into an mp4 with ffmpeg
    (zoompan + fade). Runs on the GitHub Actions ubuntu runner."""
    out = OUT_DIR / f"{out_name}.mp4"
    if not subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0:
        raise RuntimeError("ffmpeg not available (expected on GitHub runner)")

    clips = []
    with tempfile.TemporaryDirectory() as td:
        for i, img in enumerate(image_paths):
            seg = Path(td) / f"seg{i}.mp4"
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(img),
                   "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                           f"crop={width}:{height},zoompan=z='min(zoom+0.0008,1.15)':"
                           f"d={int(duration_per * 25)}:s={width}x{height}:fps=25,"
                           "format=yuv420p"),
                   "-t", str(duration_per), "-c:v", "libx264", "-preset", "veryfast",
                   str(seg)]
            subprocess.run(cmd, check=True, capture_output=True)
            clips.append(seg)

        # narration audio (optional)
        audio = None
        try:
            a = _cf_tts(narration)
            if a:
                audio = Path(td) / "narr.mp3"
                audio.write_bytes(a)
        except Exception as e:
            print(f"[media] tts skipped: {e}")

        # concat
        lst = Path(td) / "list.txt"
        lst.write_text("\n".join(f"file '{c}'" for c in clips))
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
        if audio:
            cmd += ["-i", str(audio), "-shortest",
                    "-af", "apad", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
    return out
