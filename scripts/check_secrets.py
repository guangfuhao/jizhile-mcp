"""Scan public files, Git blobs and release contents without printing secrets."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import subprocess
import tarfile
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
PATTERNS = [re.compile(rb"JZLeaf[A-Za-z0-9]{8,}"), re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
            re.compile(rb"ark-[a-f0-9]{8}-[a-f0-9-]{20,}"),
            re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")]


def secret_values(local_config: bool) -> list[bytes]:
    values = [os.environ.get("JIZHILE_API_KEY", ""), os.environ.get("JIZHILE_VERIFYCODE", ""),
              os.environ.get("JIZHILE_ARK_API_KEY", ""), os.environ.get("ARK_API_KEY", ""),
              os.environ.get("JIZHILE_YDDM_API_KEY", "")]
    if local_config:
        path = Path(os.environ.get("JIZHILE_CONFIG_FILE", "~/.config/jizhile-mcp/credentials.json")).expanduser()
        if path.exists():
            raw = json.loads(path.read_text())
            values += [raw.get("api_key", ""), raw.get("verifycode", "")]
        ark_path = Path(os.environ.get("JIZHILE_ARK_CONFIG_FILE", "~/.config/jizhile-mcp/ark-credentials.json")).expanduser()
        if ark_path.exists():
            values.append(json.loads(ark_path.read_text()).get("api_key", ""))
        cloud_path = Path(os.environ.get("JIZHILE_YDDM_CONFIG_FILE", "~/.config/jizhile-mcp/yddm-credentials.json")).expanduser()
        if cloud_path.exists():
            values.append(json.loads(cloud_path.read_text()).get("api_key", ""))
    result = []
    for value in values:
        if isinstance(value, str) and value:
            result += [value.encode(), urllib.parse.quote(value, safe="").encode(), base64.b64encode(value.encode())]
    return result


def scan(local_config: bool = False) -> dict:
    secrets = secret_values(local_config)
    hits = []; files_checked = blobs_checked = archives_checked = 0

    def check(data: bytes, label: str):
        if any(s in data for s in secrets) or any(p.search(data) for p in PATTERNS):
            hits.append(label)

    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or set(relative.parts) & SKIP or relative.parts[:2] == ("docs", "api"):
            continue
        if relative.parts[0] == "dist":
            if path.suffix in ("zip", ".zip", ".whl"):
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        check(archive.read(name), f"artifact:{path.name}:{name}"); archives_checked += 1
            elif path.name.endswith(".tar.gz"):
                with tarfile.open(path) as archive:
                    for member in archive.getmembers():
                        if member.isfile():
                            check(archive.extractfile(member).read(), f"artifact:{path.name}:{member.name}"); archives_checked += 1
            else:
                check(path.read_bytes(), f"artifact:{path.name}")
        else:
            check(path.read_bytes(), str(relative)); files_checked += 1
    if (ROOT / ".git").exists():
        rows = subprocess.check_output(["git", "rev-list", "--objects", "--all"], cwd=ROOT).splitlines()
        for row in rows:
            sha = row.split(b" ", 1)[0]
            kind = subprocess.check_output(["git", "cat-file", "-t", sha.decode()], cwd=ROOT).strip()
            if kind == b"blob":
                check(subprocess.check_output(["git", "cat-file", "blob", sha.decode()], cwd=ROOT), "git-blob:" + sha.decode())
                blobs_checked += 1
    return {"ok": not hits, "files_checked": files_checked, "git_blobs_checked": blobs_checked,
            "archive_members_checked": archives_checked, "findings": sorted(set(hits))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-config", action="store_true")
    args = parser.parse_args()
    result = scan(args.local_config)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
