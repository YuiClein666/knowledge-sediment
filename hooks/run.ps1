# knowledge-sediment · Stop/FinalStop hook 启动器（Windows PowerShell）
#
# 为什么需要它：hook 的执行环境不保证 `python` 在 PATH 里（平台自己的插件也刻意
# 只依赖 bash/PowerShell）。本脚本负责按优先级找到可用的 Python 解释器，再调用
# auto_sediment.py。
#
# 铁律：
#   1. 无论任何情况都 exit 0 —— 绝不影响会话
#   2. 正常情况下不输出任何内容（`suppressOutput`）
#   3. 找不到 Python 就静默退出，不做任何事

# -Silent：只做后台工作，绝不向会话输出任何内容
# （用于 Stop 事件——那里的输出会被当作"是否继续对话"的判据，必须保持绝对安静）
param([switch]$Silent)

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

function Resolve-PythonInterpreter {
    # 1) 安装时写入的配置（最可靠）
    $cfgPath = Join-Path $env:USERPROFILE '.workbuddy\knowledge-sediment.json'
    if (Test-Path -LiteralPath $cfgPath) {
        try {
            $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.python -and (Test-Path -LiteralPath $cfg.python)) { return $cfg.python }
        } catch { }
    }

    # 2) 环境变量
    if ($env:KNOWLEDGE_SEDIMENT_PYTHON -and (Test-Path -LiteralPath $env:KNOWLEDGE_SEDIMENT_PYTHON)) {
        return $env:KNOWLEDGE_SEDIMENT_PYTHON
    }

    # 3) WorkBuddy 托管 Python（venv 优先，其次版本目录，取最高版本）
    $envRoot = Join-Path $env:USERPROFILE '.workbuddy\binaries\python'
    foreach ($p in @(
            (Join-Path $envRoot 'envs\default\Scripts\python.exe'),
            (Join-Path $envRoot 'envs\default\bin\python'))) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $verDir = Join-Path $envRoot 'versions'
    if (Test-Path -LiteralPath $verDir) {
        $cands = Get-ChildItem -LiteralPath $verDir -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path -LiteralPath $_ }
        if ($cands.Count -gt 0) { return $cands[0] }
    }

    # 4) 最后兜底：PATH 上的 python
    foreach ($name in @('python', 'python3', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { return $cmd.Source }
    }
    return $null
}

$pluginRoot = $env:CODEBUDDY_PLUGIN_ROOT
if ([string]::IsNullOrWhiteSpace($pluginRoot)) {
    $pluginRoot = Split-Path -Parent $PSScriptRoot
}

$sedimentScript = Join-Path $pluginRoot 'scripts\auto_sediment.py'
if (-not (Test-Path -LiteralPath $sedimentScript)) { exit 0 }

# 全局开关
if ($env:KNOWLEDGE_SEDIMENT_ENABLE -eq '0') { exit 0 }

$python = Resolve-PythonInterpreter
if (-not $python) { exit 0 }

try {
    $result = & $python $sedimentScript --mode remind 2>$null
    $text = ($result | Out-String).Trim()
} catch {
    exit 0
}

# 只有在确有内容时才输出，且包装成 hook JSON（suppressOutput 保持静默）
if ($Silent) { exit 0 }

if ($text) {
    $payload = @{
        suppressOutput      = $true
        hookSpecificOutput  = @{
            hookEventName    = 'FinalStop'
            additionalContext = $text
        }
    }
    $payload | ConvertTo-Json -Depth 5 -Compress
}

exit 0
