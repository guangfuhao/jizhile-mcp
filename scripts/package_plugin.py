"""Assemble a credential-free portable bundle inside the marketplace root."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "bundle"
if out.is_symlink():
    raise RuntimeError("Refusing to replace a symlink")
if out.exists():
    shutil.rmtree(out)
out.mkdir()
for name in ("plugin.json", "mcp.json", "pyproject.toml", "uv.lock", "README.md", "README.en.md", "LICENSE"):
    shutil.copy2(ROOT / name, out / name)
for name in ("src", "skills"):
    shutil.copytree(ROOT / name, out / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(out / "scripts").mkdir()
for name in ("run_mcp.sh", "mcp_smoke.py"):
    shutil.copy2(ROOT / "scripts" / name, out / "scripts" / name)
(out / "docs").mkdir()
shutil.copy2(ROOT / "docs/sources.json", out / "docs/sources.json")
shutil.copy2(ROOT / "docs/live-test-receipt.json", out / "docs/live-test-receipt.json")
print(out)
