#!/usr/bin/env bash
# knowledge-sediment 一键安装（macOS / Linux）
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/YuiClein666/knowledge-sediment/main/bootstrap.sh | bash
set -e

echo "=== knowledge-sediment 一键安装 ==="

# 0) 前置检查
command -v git >/dev/null 2>&1 || { echo "✗ 未找到 git，请先安装"; exit 1; }
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || {
  echo "✗ 未找到 python，请先安装 Python 3.9+"; exit 1; }

# 1) 克隆或更新工具仓库
DEST="$HOME/knowledge-sediment"
if [ -d "$DEST/.git" ]; then
  echo "[1/2] 更新已有仓库：$DEST"
  git -C "$DEST" pull --ff-only
else
  echo "[1/2] 克隆工具仓库到：$DEST"
  git clone https://github.com/YuiClein666/knowledge-sediment.git "$DEST"
fi
[ -f "$DEST/scripts/kb.py" ] || { echo "✗ 仓库克隆失败"; exit 1; }

# 2) 安装到所有检测到的 agent
echo "[2/2] 检测并安装到本机 agent..."
bash "$DEST/kb.sh" install || RC=$?

echo ""
echo "=== 完成 ==="
echo "常用命令："
echo "  bash $DEST/kb.sh init        # 在某个工作区开启沉淀"
echo "  bash $DEST/kb.sh install     # 装/重装到检测到的 agent"
echo "  bash $DEST/kb.sh update      # 自更新"
echo "  bash $DEST/kb.sh doctor      # 体检"
echo "对 agent 说一句「沉淀一下：...」即可开始沉淀知识。"
exit ${RC:-0}
