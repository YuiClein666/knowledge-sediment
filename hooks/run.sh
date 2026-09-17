#!/usr/bin/env bash
# knowledge-sediment · hook 启动器（POSIX shell；在本平台中是唯一可靠的入口）
#
# 为什么需要它：hook 的执行环境不保证 `python` 在 PATH 里，也不保证路径格式统一。
# 本脚本负责：① 找到能用的 Python 解释器 ② 把路径转换成该解释器认识的格式 ③ 调用脚本。
#
# 铁律：
#   1. 无论如何都 exit 0 —— 绝不影响会话
#   2. 正常情况零输出
#   3. 找不到 Python 静默退出
#   4. 只依赖 POSIX shell 内建能力
#
# ★ 血泪教训（三个都踩过）：
#   · 本平台把 ${CODEBUDDY_PLUGIN_ROOT} 展开成 POSIX 风格路径（/c/Users/...），
#     直接交给 Windows PowerShell 的 -File 会被拒绝（"格式不正确"）→ 所以不要用 PowerShell 入口
#   · 同一个 POSIX 路径也不能直接喂给 Windows 版的 python.exe（会被当成 C:\c\Users\...）
#     → 必须把脚本路径转成 Windows 格式（to_native_path）
#   · 配置 JSON 里的反斜杠是转义的（C:\\Users\\...），解析后要还原，否则路径里会出现双斜杠

set +e

# --silent   ：只做后台工作，绝不输出（用于 FinalStop —— 那里的输出会被平台丢弃）
# --emit-json：把提示包成 hook 信封后输出（用于 UserPromptSubmit —— 只有这类事件
#              支持 hookSpecificOutput.additionalContext，能把内容真正注入对话上下文）
SILENT=0
EMIT="text"
for arg in "$@"; do
  case "$arg" in
    --silent) SILENT=1 ;;
    --emit-json) EMIT="json" ;;
  esac
done

# 全局开关
[ "${KNOWLEDGE_SEDIMENT_ENABLE:-1}" = "0" ] && exit 0

PLUGIN_ROOT="${CODEBUDDY_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SEDIMENT_SCRIPT="$PLUGIN_ROOT/scripts/auto_sediment.py"
[ -f "$SEDIMENT_SCRIPT" ] || exit 0

# 把 POSIX 路径转成 Windows 路径（/c/Users/x → C:/Users/x）；非 Windows 形态原样返回
to_native_path() {
  case "$1" in
    /[a-zA-Z]/*)
      _d=$(printf '%s' "$1" | cut -c2 | tr 'a-z' 'A-Z')
      _rest=$(printf '%s' "$1" | cut -c3-)
      printf '%s:/%s' "$_d" "$_rest"
      ;;
    *) printf '%s' "$1" ;;
  esac
}

find_config_file() {
  # 新标准位置优先（与 Agent 无关，换工具不用重配）；兼容旧位置
  for c in "$HOME/.knowledge-sediment/config.json" \
           "$HOME/.workbuddy/knowledge-sediment.json"; do
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

find_python() {
  # 1) 安装时写入的配置（最可靠）
  cfg=$(find_config_file)
  if [ -n "$cfg" ] && [ -f "$cfg" ]; then
    # 取出 python 字段，并把 JSON 转义的反斜杠还原成单反斜杠
    p=$(sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$cfg" \
        | head -n 1 | sed 's/\\\\/\\/g')
    if [ -n "$p" ]; then
      # 原样试一次（可能是 Windows 路径）；不行再转成 POSIX 形态试一次
      if [ -x "$p" ]; then printf '%s' "$p"; return 0; fi
      case "$p" in
        [A-Za-z]:[/\\]*)
          _pd=$(printf '%s' "$p" | cut -c1 | tr 'A-Z' 'a-z')
          _prest=$(printf '%s' "$p" | cut -c3- | tr '\\' '/')
          p2="/$_pd$_prest"
          [ -x "$p2" ] && { printf '%s' "$p2"; return 0; }
          ;;
      esac
    fi
  fi

  # 2) 环境变量
  if [ -n "${KNOWLEDGE_SEDIMENT_PYTHON:-}" ] && [ -x "${KNOWLEDGE_SEDIMENT_PYTHON}" ]; then
    printf '%s' "$KNOWLEDGE_SEDIMENT_PYTHON"; return 0
  fi

  # 3) WorkBuddy 托管 Python（venv 优先，其次取最高版本）
  for p in \
    "$HOME/.workbuddy/binaries/python/envs/default/bin/python" \
    "$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"; do
    [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  done
  if [ -d "$HOME/.workbuddy/binaries/python/versions" ]; then
    p=$(ls -1d "$HOME"/.workbuddy/binaries/python/versions/*/bin/python \
                  "$HOME"/.workbuddy/binaries/python/versions/*/python.exe 2>/dev/null \
        | sort -r | head -n 1)
    [ -n "$p" ] && [ -x "$p" ] && { printf '%s' "$p"; return 0; }
  fi

  # 4) PATH 兜底
  for name in python3 python py; do
    if command -v "$name" >/dev/null 2>&1; then
      command -v "$name"; return 0
    fi
  done
  return 1
}

PY=$(find_python) || exit 0
[ -n "$PY" ] || exit 0

# Windows 版解释器只认 Windows 风格的脚本路径
case "$PY" in
  *.exe|*.EXE) SCRIPT_ARG=$(to_native_path "$SEDIMENT_SCRIPT") ;;
  *)           SCRIPT_ARG="$SEDIMENT_SCRIPT" ;;
esac

# 配置里若写了知识库路径，传给脚本（让脚本确定性定位，不靠推断）
KB_ARG=""
_cfg=$(find_config_file)
if [ -n "$_cfg" ]; then
  _kb=$(sed -n 's/.*"kb"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$_cfg" 2>/dev/null | head -n 1 | sed 's/\\\\/\\/g')
  [ -n "$_kb" ] && KB_ARG="$_kb"
fi

# ★ 保留 stderr 到诊断日志，避免再次出现"静默失败却看起来像成功"
DIAG="$HOME/.workbuddy/logs/knowledge-sediment-hook.err"

ARGS=(--mode remind)
[ "$EMIT" = "json" ] && ARGS+=(--emit json --event UserPromptSubmit)
[ -n "$KB_ARG" ] && ARGS+=(--kb "$KB_ARG")

OUT=$("$PY" "$SCRIPT_ARG" "${ARGS[@]}" 2>>"$DIAG")
RC=$?

if [ "$RC" -ne 0 ]; then
  {
    printf '[%s] launcher: script exited %s\n  python=%s\n  script=%s\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "$RC" "$PY" "$SCRIPT_ARG"
    printf '  kb=%s\n' "$KB_ARG"
  } >>"$DIAG" 2>/dev/null
  exit 0
fi

# 有内容才输出（保持静默时零输出）
if [ "$SILENT" -eq 0 ] && [ -n "$OUT" ]; then
  printf '%s\n' "$OUT"
fi

exit 0
