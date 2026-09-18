#!/usr/bin/env bash
# kb - knowledge-sediment command entry (macOS / Linux / Git Bash)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Windows 环境（Git Bash / 便携 bash）下，Windows 版 python.exe 不认
# POSIX 风格路径（/c/Users/...），必须转换为 C:/Users/... 再传参
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    SDIR="$(printf '%s' "$DIR" | sed -E 's#^/([a-zA-Z])/#\1:/#')"
    ;;
  *)
    SDIR="$DIR"
    ;;
esac

for c in python3 python; do
  command -v "$c" >/dev/null 2>&1 || continue
  exec "$c" -X utf8 "$SDIR/scripts/kb.py" "$@"
done
echo "[kb] Python not found. Install Python 3.9+ first." >&2
exit 1
