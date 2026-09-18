# knowledge-sediment 一键安装（Windows / PowerShell）
# 用法：在 PowerShell 里执行
#   irm https://raw.githubusercontent.com/YuiClein666/knowledge-sediment/main/bootstrap.ps1 | iex
# 自动：克隆（或更新）工具仓库 -> 检测本机已安装的 agent -> 全部装上
$ErrorActionPreference = "Stop"

Write-Host "=== knowledge-sediment 一键安装 ===" -ForegroundColor Cyan

# 0) 前置检查
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "✗ 未找到 git，请先安装：https://git-scm.com/downloads" -ForegroundColor Red
    exit 1
}

# 1) 克隆或更新工具仓库
$dest = Join-Path $HOME "knowledge-sediment"
if (Test-Path (Join-Path $dest ".git")) {
    Write-Host "[1/2] 更新已有仓库：$dest"
    git -C $dest pull --ff-only
} else {
    Write-Host "[1/2] 克隆工具仓库到：$dest"
    git clone https://github.com/YuiClein666/knowledge-sediment.git $dest
}
if (-not (Test-Path (Join-Path $dest "scripts\kb.py"))) {
    Write-Host "✗ 仓库克隆失败" -ForegroundColor Red
    exit 1
}

# 2) 安装到所有检测到的 agent
Write-Host "[2/2] 检测并安装到本机 agent..."
& (Join-Path $dest "kb.cmd") install
$code = $LASTEXITCODE

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Cyan
Write-Host "常用命令（在仓库目录或任意位置）："
Write-Host "  $dest\kb.cmd init        # 在某个工作区开启沉淀"
Write-Host "  $dest\kb.cmd install     # 装/重装到检测到的 agent"
Write-Host "  $dest\kb.cmd update      # 自更新"
Write-Host "  $dest\kb.cmd doctor      # 体检"
Write-Host "对 agent 说一句「沉淀一下：...」即可开始沉淀知识。"
exit $code
