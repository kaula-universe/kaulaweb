#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_native.py — Kaula WebUI native 构建脚本（Python 版）

用法示例：
  python build_native.py <示例 .kl 路径>
  python build_native.py ..\\backends\\backend_smoke.kl
  python build_native.py "E:\\Users\\tf\\Desktop\\新建文件夹\\kaula-webui\\backends\\backend_smoke.kl"

说明：
  - kaulac.exe 必须在 kaula\\kaula-compiler 目录下调用（其 cache/ 与
    pkglib 相对配置依赖该工作目录），故脚本把 subprocess 的 cwd 设为该目录。
  - 中文路径处理：把目标 .kl 转成相对 kaula-compiler 的相对路径传入，
    避免命令行编码问题。
  - 产物归集：kaulac 把 exe 生成在【源文件所在目录】（不落在编译器目录）。
    例如编译 ..\\..\\kaula-webui\\backends\\backend_smoke.kl，
    产物为 ..\\..\\kaula-webui\\backends\\backend_smoke.exe。
"""

import argparse
import os
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
  python build_native.py "E:\\Users\\tf\\Desktop\\新建文件夹\\kaula-webui\\backends\\backend_smoke.kl"
  python build_native.py ..\\backends\\backend_smoke.kl --compiler-dir "E:\\path\\to\\kaula\\kaula-compiler"
"""


def default_compiler_dir() -> Path:
    """脚本位于 kaula-webui/build/，编译器在 ../../kaula/kaula-compiler。"""
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "kaula" / "kaula-compiler"


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
        "--compiler-dir",
        default=None,
        help="kaula-compiler 目录（默认自动定位：脚本上级目录的 ../kaula/kaula-compiler）",
    )
    return parser.parse_args()


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

    # 3. 切到编译器目录，转相对路径调用（规避中文路径编码问题）
    try:
        rel = os.path.relpath(src_abs, compiler_dir)
    except ValueError:
        # 跨盘符等无法计算相对路径时回退为绝对路径
        rel = str(src_abs)

    print(f"[build] cwd    = {compiler_dir}")
    print(f"[build] source = {rel}")
    proc = subprocess.run([str(kaulac), rel], cwd=str(compiler_dir))
    if proc.returncode != 0:
        print(f"错误: kaulac compile failed (exit {proc.returncode})", file=sys.stderr)
        return proc.returncode

    # 4. 产物归集：exe 生成在源文件目录
    exe_abs = src_abs.with_suffix(".exe")
    if exe_abs.is_file():
        print(f"[build] SUCCESS -> {exe_abs}")
        return 0

    print(f"错误: compile reported success but exe not found: {exe_abs}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
