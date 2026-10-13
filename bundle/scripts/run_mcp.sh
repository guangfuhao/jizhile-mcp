#!/bin/sh
set -eu
PLUGIN_ROOT="${PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
if [ -x "$PLUGIN_ROOT/.venv/bin/jizhile-mcp" ]; then
  exec "$PLUGIN_ROOT/.venv/bin/jizhile-mcp" "$@"
fi
if command -v uv >/dev/null 2>&1; then
  exec uv run --frozen --project "$PLUGIN_ROOT" jizhile-mcp "$@"
fi
if [ -x /opt/homebrew/bin/uv ]; then
  exec /opt/homebrew/bin/uv run --frozen --project "$PLUGIN_ROOT" jizhile-mcp "$@"
fi
echo 'uv is required: install uv, then run uv sync --frozen in the plugin directory.' >&2
exit 1
