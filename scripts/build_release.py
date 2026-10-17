"""Package the generated bundle as a standalone Codex marketplace ZIP."""
from pathlib import Path
import hashlib
import json
import runpy
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "scripts/package_plugin.py"))
version = json.loads((ROOT / "plugin.json").read_text())["version"]
prefix = f"jizhile-mcp-{version}"
out = ROOT / "dist" / f"{prefix}-plugin.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((ROOT / "bundle").rglob("*")):
        if path.is_file():
            archive.write(path, f"{prefix}/plugin/{path.relative_to(ROOT / 'bundle')}")
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    marketplace["plugins"][0]["source"]["path"] = "./plugin"
    archive.writestr(f"{prefix}/.agents/plugins/marketplace.json", json.dumps(marketplace, ensure_ascii=False, indent=2))
python_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
assets = [out, out.parent / f"jizhile_mcp-{python_version}-py3-none-any.whl", out.parent / f"jizhile_mcp-{python_version}.tar.gz"]
(out.parent / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets))
print(out)
