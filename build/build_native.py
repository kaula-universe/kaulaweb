#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_native.py — Kaula WebUI native 构建脚本（Python 版）

用法示例：
  python build_native.py <示例 .kl 路径> [-o OUTPUT_DIR]
  python build_native.py ..\\backends\\backend_smoke.kl
  python build_native.py "E:\\Users\\tf\\Desktop\\新建文件夹\\kaula-webui\\examples\\todo_native.kl"

说明：
  - kaulac.exe 必须在 kaula\\kaula-compiler 目录下调用（其 cache/ 与
    pkglib 相对配置依赖该工作目录），故脚本把 subprocess 的 cwd 设为该目录。
  - 中文路径处理：把目标 .kl 转成相对 kaula-compiler 的相对路径传入，
    避免命令行编码问题。
  - 产物归集：产物默认归集到 kaula-webui\\dist\\native\\，保持 examples
    源码目录整洁；可用 -o/--output-dir 覆盖归集位置。
    【实测结论（2026-08-10）】kaulac 的 -output-dir 旗标（internal/config/
    config.go）仅在配置层注册，cmd/kaulac/main.go 的 concurrentCompile
    硬编码 outputExe = inputDir+名字，旗标实际不生效——故本脚本不用
    该旗标，改为编译后移动文件后置归集（kaulac 产物落在源文件目录）。
  - 默认附加 --no-cache：kaulac 增量缓存对 import 变更失效，
    修改 webui\\ / backends\\ 核心 .kl 后不附加会链到旧产物。
  - kaulac 会向 stderr 输出 [SEMA DEBUG] 等调试行，不影响成败判定：
    本脚本只以进程 returncode 判定（Python 天然无 PowerShell 的
    NativeCommandError 问题）。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows GBK 控制台下强制 UTF-8 输出，避免中文路径/提示乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

EXAMPLES = """\
示例:
  python build_native.py ..\\backends\\backend_smoke.kl
  python build_native.py ..\\examples\\counter_native.kl -o D:\\release
  python build_native.py ..\\backends\\backend_smoke.kl --compiler-dir "E:\\path\\to\\kaula\\kaula-compiler"
"""


def default_compiler_dir() -> Path:
    """脚本位于 kaula-webui/build/，当前编译器实际位于 ../../kaula/ 下的 kaulac.exe。"""
    script_dir = Path(__file__).resolve().parent
    root_dir = script_dir.parent.parent / "kaula"
    if (root_dir / "kaulac.exe").is_file():
        return root_dir
    compiler_dir = root_dir / "kaula-compiler"
    if (compiler_dir / "kaulac.exe").is_file():
        return compiler_dir
    return root_dir


def default_output_dir() -> Path:
    """归集目录默认 kaula-webui/dist/native/（kaula-webui = build/ 的上一级）。"""
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent / "dist" / "native"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kaula WebUI native 构建：调用 kaulac.exe 编译指定 .kl 为原生 exe。",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        help="入口 .kl 源文件路径（必填）",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="产物归集目录（默认 kaula-webui/dist/native/）",
    )
    parser.add_argument(
        "--compiler-dir",
        default=None,
        help="kaula-compiler 目录（默认自动定位：脚本上级目录的 ../kaula/kaula-compiler）",
    )
    return parser.parse_args()


def find_vc_dev_cmd() -> Path | None:
    """查找 VS 的 vcvars64.bat / VsDevCmd.bat，优先返回可用于激活 MSVC 环境的脚本。"""
    candidates = [
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"),
    ]
    for p in candidates:
        if p.is_file():
            return p

    # VsDevCmd.bat 依赖 vswhere.exe，它通常位于 VS Installer 目录；如果缺失，说明安装不完整。
    installer_dir = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer")
    if not installer_dir.is_dir():
        installer_dir = Path(r"C:\Program Files\Microsoft Visual Studio\Installer")
    vswhere = installer_dir / "vswhere.exe"
    if vswhere.is_file():
        for p in [
            Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"),
            Path(r"C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat"),
            Path(r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat"),
            Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"),
        ]:
            if p.is_file():
                return p
    return None


def main() -> int:
    args = parse_args()

    # 1. 定位编译器目录
    compiler_dir = (
        Path(args.compiler_dir).resolve() if args.compiler_dir else default_compiler_dir()
    )
    kaulac = compiler_dir / "kaulac.exe"
    if not kaulac.is_file():
        print(f"错误: kaulac.exe not found in: {compiler_dir}", file=sys.stderr)
        return 1

    # 2. 解析源文件为绝对路径并校验
    src_abs = Path(args.source).resolve()
    if not src_abs.is_file():
        print(f"错误: source not found: {src_abs}", file=sys.stderr)
        return 1

    # 3. 归集目录
    out_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 4. 切到编译器目录，转相对路径调用（规避中文路径编码问题）
    try:
        rel = os.path.relpath(src_abs, compiler_dir)
    except ValueError:
        # 跨盘符等无法计算相对路径时回退为绝对路径
        rel = str(src_abs)

    print(f"[build] cwd        = {compiler_dir}")
    print(f"[build] source     = {rel}")
    print(f"[build] output-dir = {out_dir}")

    vc_env = find_vc_dev_cmd()
    command = [str(kaulac), "--no-cache", rel]
    if vc_env is not None:
        installer_dir = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer")
        if not installer_dir.is_dir():
            installer_dir = Path(r"C:\Program Files\Microsoft Visual Studio\Installer")
        installer_dir = str(installer_dir)
        cmd = (
            f'cmd /d /s /c "set PATH=%PATH%;{installer_dir} && call \"{vc_env}\" >nul && '
            f'\"{kaulac}\" --no-cache --target-triple x86_64-pc-windows-msvc \"{rel}\""'
        )
        print(f"[build] activating VC toolchain: {vc_env}")
        proc = subprocess.run(cmd, cwd=str(compiler_dir), shell=True)
    else:
        print("[build] warning: no VS vcvars64.bat/VsDevCmd.bat found; native webview link may fail without a configured MSVC toolchain.")
        # 默认 --no-cache：增量缓存对 import 变更失效（见文件头）；
        # kaulac stderr 的 [SEMA DEBUG] 不影响判定，只看 returncode
        proc = subprocess.run(command, cwd=str(compiler_dir))

    if proc.returncode != 0:
        print(f"错误: kaulac compile failed (exit {proc.returncode})", file=sys.stderr)
        return proc.returncode

    # 5. 产物归集：kaulac 把 exe 生成在源文件目录，移动到归集目录
    src_exe = src_abs.with_suffix(".exe")
    if not src_exe.is_file():
        print(f"错误: compile reported success but exe not found: {src_exe}", file=sys.stderr)
        return 1
    exe_abs = out_dir / src_exe.name
    shutil.move(str(src_exe), str(exe_abs))
    print(f"[build] SUCCESS -> {exe_abs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
