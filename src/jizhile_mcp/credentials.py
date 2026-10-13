from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path


def config_path() -> Path:
    return Path(os.environ.get("JIZHILE_CONFIG_FILE", "~/.config/jizhile-mcp/credentials.json")).expanduser()


def save_credentials(api_key: str, verifycode: str = "") -> None:
    if not api_key.strip() or len(api_key) > 256:
        raise ValueError("API Key 为空或长度不合法")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump({"api_key": api_key.strip(), "verifycode": verifycode.strip()}, out)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def credentials() -> dict:
    try:
        stored = json.loads(config_path().read_text())
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {"api_key": os.getenv("JIZHILE_API_KEY") or stored.get("api_key", ""),
            "verifycode": os.getenv("JIZHILE_VERIFYCODE") or stored.get("verifycode", "")}


def snapshot() -> dict:
    return {"configured": bool(credentials()["api_key"]), "api_key": "••••••••" if credentials()["api_key"] else "",
            "config_file": str(config_path()), "api_host": "https://www.dajiala.com"}


def main() -> None:
    save_credentials(getpass.getpass("极致了 API Key（隐藏输入）: "), getpass.getpass("附加码（可留空）: "))
    print("配置已保存在本机，权限 0600。")
