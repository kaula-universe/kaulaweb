# ============================================================
# build_web.ps1 — Kaula WebUI WASM 构建脚本（PowerShell 5.1 封装）
# ------------------------------------------------------------
# 用法（与 build_web.py 完全一致，任意工作目录下均可）：
#   .\build_web.ps1 <入口 .kl 路径> [-o OUTPUT_DIR]
#   .\build_web.ps1 ..\backends\backend_wasm.kl
#   .\build_web.ps1 ..\examples\counter_web.kl -o ..\dist\web\counter_web
#
# 说明：
#   - 本脚本只是 build_web.py 的 PowerShell 封装：把入口 .kl 解析为
#     绝对路径后，连同其余参数原样转发给 python build_web.py，
#     保证行为与 py 版完全一致（kaulac -> std 模块推导 -> emcc 链接
#     -> 产物校验 -> node wasm 校验，全部由 py 版完成）。
#   - emcc 不在 PATH 也无妨：build_web.py 内部已用 tools\emsdk 的
#     绝对路径定位 emcc.exe。
#   - 透传支持的可选参数：-o/--output-dir、--emcc、--skip-node-check。
# ============================================================
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Source,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript  = Join-Path $scriptDir 'build_web.py'
if (-not (Test-Path $pyScript)) {
    Write-Error "build_web.py not found: $pyScript"
    exit 1
}

# 解析入口 .kl 为绝对路径（py 版内部会基于绝对路径做校验与推导）
try {
    $srcAbs = (Resolve-Path $Source).Path
} catch {
    Write-Error "source not found: $Source"
    exit 1
}
if (-not (Test-Path $srcAbs)) {
    Write-Error "source not found: $srcAbs"
    exit 1
}

# 转发给 python build_web.py（工作目录不变，py 版自行处理 cwd 切换）
$pyArgs = @($pyScript, $srcAbs)
if ($ExtraArgs) { $pyArgs += $ExtraArgs }

& python @pyArgs
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    Write-Error "build_web.py failed (exit $rc)"
    exit $rc
}
