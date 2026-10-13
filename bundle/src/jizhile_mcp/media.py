"""Bounded local media processing. Never pass a remote URL to ffmpeg."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class MediaError(Exception):
    pass


def public_video_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise MediaError("视频地址必须为不含账号密码的HTTPS公网直链。")
    allowed = ("video.qq.com", "weixin.qq.com", "qpic.cn")
    allowed += tuple(x.strip().lower() for x in os.getenv("JIZHILE_VIDEO_HOSTS", "").split(",") if x.strip())
    host = parsed.hostname.lower()
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise MediaError("视频域名未授权；默认仅允许微信/腾讯视频CDN。")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise MediaError("禁止访问内网、本机或非公网地址。")
    except OSError:
        raise MediaError("视频域名解析失败。") from None
    return url


def download(url: str, output: Path, max_bytes: int = 250 * 1024 * 1024) -> None:
    partial = output.with_suffix(".part")
    try:
        with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=False) as client:
            for _ in range(4):
                public_video_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        from urllib.parse import urljoin
                        url = urljoin(url, location)
                        continue
                    if response.status_code in (401, 403, 404, 410):
                        raise MediaError("视频直链不可用或已过期；需重新获取直链，不自动调用收费接口刷新。")
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared and int(declared) > max_bytes:
                        raise MediaError("视频超过250MB下载上限。")
                    total = 0
                    with partial.open("wb") as out:
                        os.chmod(partial, 0o600)
                        for block in response.iter_bytes(64 * 1024):
                            total += len(block)
                            if total > max_bytes:
                                raise MediaError("视频超过250MB下载上限。")
                            out.write(block)
                    if total == 0:
                        raise MediaError("视频下载为空。")
                    os.replace(partial, output)
                    return
            raise MediaError("视频重定向次数超限。")
    except (httpx.HTTPError, ValueError):
        raise MediaError("视频下载失败；未提交模型转写，不自动重试。") from None
    finally:
        partial.unlink(missing_ok=True)


def run_media(args: list[str], timeout: int = 180) -> str:
    executable = shutil.which(args[0])
    if not executable:
        raise MediaError(f"缺少{args[0]}，请先安装ffmpeg。")
    try:
        result = subprocess.run([executable, *args[1:]], capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise MediaError("本地音频处理超时，子进程已终止。") from None
    if result.returncode:
        raise MediaError("媒体解析失败：可能是损坏、加密视频或无音轨；未提交转写。")
    return result.stdout.decode("utf-8", errors="replace")


def probe(path: Path) -> dict:
    try:
        data = json.loads(run_media(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)]))
        duration = float(data["format"]["duration"])
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    except (ValueError, KeyError, TypeError):
        raise MediaError("无法获取有效音频时长。") from None
    if not has_audio or not 0 < duration <= 3600:
        raise MediaError("无音轨或单条视频时长超过60分钟。")
    return {"duration_seconds": duration, "has_audio": has_audio}


def extract_chunks(video: Path, work: Path, segment_seconds: int = 180) -> list[dict]:
    if not 30 <= segment_seconds <= 300:
        raise MediaError("音频分段须为30至300秒。")
    audio = work / "audio.mp3"
    run_media(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(video),
               "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(audio)])
    os.chmod(audio, 0o600)
    run_media(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(audio),
               "-map", "0:a:0", "-c", "copy", "-f", "segment", "-segment_time", str(segment_seconds),
               "-reset_timestamps", "1", str(work / "chunk-%04d.mp3")])
    chunks = []; offset = 0.0
    for path in sorted(work.glob("chunk-*.mp3")):
        os.chmod(path, 0o600)
        details = probe(path)
        if path.stat().st_size > 25 * 1024 * 1024:
            raise MediaError("音频分段超过方舟25MB输入上限。")
        chunks.append({"path": str(path), "start_seconds": round(offset, 3), **details})
        offset += details["duration_seconds"]
    if not chunks:
        raise MediaError("未能提取音频分段。")
    audio.unlink(missing_ok=True)
    return chunks
