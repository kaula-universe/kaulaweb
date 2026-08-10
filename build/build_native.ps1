# ============================================================
# build_native.ps1 — Kaula WebUI native 构建脚本（PowerShell 5.1）
# ------------------------------------------------------------
# 用法：
#   .\build_native.ps1 <示例 .kl 路径> [-OutputDir <归集目录>]
#   .\build_native.ps1 ..\backends\backend_smoke.kl
#   .\build_native.ps1 "E:\Users\tf\Desktop\新建文件夹\kaula-webui\examples\todo_native.kl"
#
# 说明：
#   - kaulac.exe 必须在 kaula\kaula-compiler 目录下调用（其 cache/ 与
#     pkglib 相对配置依赖该工作目录），故脚本先 Set-Location 过去。
#   - 中文路径处理：把目标 .kl / 输出目录转成相对 kaula-compiler 的
#     相对路径传入，避免命令行编码问题。
#   - 产物归集：产物默认归集到 kaula-webui\dist\native\，保持 examples
#     源码目录整洁；可用 -OutputDir 覆盖归集位置。
#     【实测结论（2026-08-10）】kaulac 的 -output-dir 旗标（internal/config/
#     config.go）仅在配置层注册，cmd/kaulac/main.go 的 concurrentCompile
#     硬编码 outputExe = inputDir+名字，旗标实际不生效——故本脚本不用
#     该旗标，改为编译后 Move-Item 后置归集（kaulac 产物落在源文件目录）。
#   - 默认附加 --no-cache：kaulac 增量缓存对 import 变更失效，
#     修改 webui\ / backends\ 核心 .kl 后不附加会链到旧产物。
#   - stderr 规避（既有问题）：kaulac 向 stderr 输出 [SEMA DEBUG]，
#     在 $ErrorActionPreference='Stop' 下会触发 NativeCommandError
#     中断脚本；故编译调用期间临时切为 Continue，以 $LASTEXITCODE 判定成败。
# ============================================================
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Source,
    [string]$OutputDir = ''
)

$ErrorActionPreference = 'Stop'

# 1. 定位编译器目录（脚本位于 kaula-webui\build\，编译器在 ..\..\kaula\kaula-compiler）
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$compilerDir = Join-Path (Split-Path -Parent (Split-Path -Parent $scriptDir)) 'kaula\kaula-compiler'
if (-not (Test-Path (Join-Path $compilerDir 'kaulac.exe'))) {
    Write-Error "kaulac.exe not found in: $compilerDir"
    exit 1
}

# 2. 解析源文件为绝对路径并校验
$srcAbs = (Resolve-Path $Source).Path
if (-not (Test-Path $srcAbs)) {
    Write-Error "source not found: $srcAbs"
    exit 1
}

# 3. 归集目录：默认 kaula-webui\dist\native\（kaula-webui = build\ 的上一级）
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Split-Path -Parent $scriptDir) 'dist\native'
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
$outAbs = (Resolve-Path $OutputDir).Path

# PS 5.1（.NET Framework）无 Path.GetRelativePath，用 Uri 计算相对路径
function ConvertTo-RelativePath([string]$FromDir, [string]$Target) {
    try {
        $fromUri = New-Object System.Uri($FromDir.TrimEnd('\') + '\')
        $toUri = New-Object System.Uri($Target)
        $relUri = $fromUri.MakeRelativeUri($toUri)
        if ($relUri.IsAbsoluteUri) {
            return $Target
        }
        return [System.Uri]::UnescapeDataString($relUri.ToString()).Replace('/', '\')
    } catch {
        return $Target
    }
}

# 4. 切到编译器目录，转相对路径调用（规避中文路径编码问题）
Push-Location $compilerDir
try {
    $rel = ConvertTo-RelativePath $compilerDir $srcAbs
    Write-Host "[build] cwd        = $compilerDir"
    Write-Host "[build] source     = $rel"
    Write-Host "[build] output-dir = $outAbs"
    # 临时 Continue：规避 kaulac stderr [SEMA DEBUG] 触发 NativeCommandError；
    # 成败以 $LASTEXITCODE 判定（既有问题的标准规避方式）。
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & .\kaulac.exe --no-cache $rel
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $oldEAP
    if ($rc -ne 0) {
        Write-Error "kaulac compile failed (exit $rc)"
        exit $rc
    }
} finally {
    Pop-Location
}

# 5. 产物归集：kaulac 把 exe 生成在源文件目录，Move-Item 归集到 dist\native\
$exeName = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetFileName($srcAbs), '.exe')
$srcExe = Join-Path (Split-Path -Parent $srcAbs) $exeName
if (-not (Test-Path $srcExe)) {
    Write-Error "compile reported success but exe not found: $srcExe"
    exit 1
}
$exeAbs = Join-Path $outAbs $exeName
Move-Item -Path $srcExe -Destination $exeAbs -Force
Write-Host "[build] SUCCESS -> $exeAbs"
