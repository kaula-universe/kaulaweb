#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# build_web.py — Kaula WebUI WASM 构建脚本（任务 #10）
# ------------------------------------------------------------
# 用法（任意工作目录下均可）：
#   python build_web.py <入口 .kl 路径> [-o OUTPUT_DIR]
#   python build_web.py ..\backends\backend_wasm.kl
#   python build_web.py ..\examples\counter_web.kl -o ..\dist\web\counter_web
#
# 流程：
#   1) Set cwd 到 kaula\kaula-compiler，调
#      kaulac.exe --no-cache --cflags "<wasm_shim.c 绝对路径>" "<入口>"
#      生成 cache\<入口名>.c（kaulac 的 cache/pkglib 相对配置依赖该 cwd）。
#      --cflags 带上 wasm_shim.c 是为了让 kaulac 内置的 native C 验证链接
#      通过（kw_shim_* 符号由该文件的 printf 回退桩提供；见 backend_wasm.kl
#      头部说明）。
#   2) 从生成的 C 的 #include "mod/xxx.h" 自动推导所需 std 模块，
#      与 BASE_STD_MODULES 显式清单取并集（见下方扩展说明）
#   3) subprocess 调 emcc.exe 编译：生成 C + wasm_shim.c + kaula/src 运行时
#      + std 模块 .c -> <入口名>.html/.js/.wasm 输出到 OutputDir
#   4) 校验产物齐全并打印路径/大小，node 快速验证 wasm 可编译加载
#
# std 模块清单策略（自动推导 + 显式基线）：
#   - BASE_STD_MODULES 是保底显式清单：io/string/container/time。
#     container 目录下的全部 .c（container.c + container_ext.c）都会参与链接。
#   - 自动推导：正则提取生成 C 中 #include "mod/..." 的 mod 名并入集合。
#   - 扩展方式：若新程序 import 了推导不到的模块，直接往
#     BASE_STD_MODULES 里加模块名即可；或确保 .kl 的 import 反映在
#     生成 C 的 #include 中（推导会自动捕获）。
#
# 硬约束（已实测验证，勿改）：
#   - 禁止链接 kaula\src\queue.c：priority_queue_create/destroy 与
#     std\container\container.c 重复定义（wasm-ld duplicate symbol）。
#   - 禁止链接 std.web / std.net 模块（WASM 后端无进程/网络桥）。
#   - 必须 -sALLOW_MEMORY_GROWTH：kmm_v4 的 mmap 路径在 Emscripten 下
#     依赖堆增长，默认 16MB 线性内存会 OOM abort。
# ============================================================

import argparse
import os
import re
import shutil
import subprocess
import sys

# Windows 控制台默认 cp936 会把 UTF-8 中文打成乱码，统一强制 UTF-8 输出
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))          # kaula-webui\build
WEBUI_DIR = os.path.dirname(SCRIPT_DIR)                          # kaula-webui
REPO_ROOT = os.path.dirname(WEBUI_DIR)                           # 工作区根
COMPILER_DIR = os.path.join(REPO_ROOT, 'kaula', 'kaula-compiler')
KAULA_SRC_DIR = os.path.join(REPO_ROOT, 'kaula', 'src')
KAULA_STD_DIR = os.path.join(REPO_ROOT, 'kaula', 'std')
WASM_SHIM_C = os.path.join(WEBUI_DIR, 'backends', 'wasm_shim.c')
DEFAULT_EMCC = os.path.join(REPO_ROOT, 'tools', 'emsdk', 'upstream',
                            'emscripten', 'emcc.exe')
EMSDK_NODE = os.path.join(REPO_ROOT, 'tools', 'emsdk', 'node',
                          '24.19.0_64bit', 'node.exe')

# 保底显式清单（counter/demo 级应用足够；扩展时在此追加模块名）
BASE_STD_MODULES = ['io', 'string', 'container', 'time']

# kaula/src 中必须参与链接的运行时文件（禁止加 queue.c，见文件头）
RUNTIME_SRC_FILES = [
    'kmm_scoped_allocator_v4.c',
    'spend_call.c',
    'allocator.c',
]

# 浏览器事件桥所需的导出符号
EXPORTED_FUNCTIONS = [
    '_main',
    '_kw_shim_event',
    '_kw_shim_show_html',
    '_kw_shim_eval',
    '_kw_shim_inject_shell',
    '_kw_shim_install_event_bridge',
    '_malloc',
    '_free',
]
EXPORTED_RUNTIME_METHODS = ['UTF8ToString', 'stringToUTF8', 'lengthBytesUTF8']

# WASM 后端禁止链接的 std 模块
FORBIDDEN_MODULES = {'web', 'net'}


def fail(msg):
    print('[build_web] ERROR: %s' % msg, file=sys.stderr)
    sys.exit(1)


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024.0 or unit == 'GB':
            return '%.1f%s' % (n, unit) if unit != 'B' else '%dB' % n
        n /= 1024.0


def run(cmd, cwd):
    """透传输出地执行命令，返回 returncode"""
    print('[build_web] $ %s' % ' '.join('"%s"' % c if ' ' in c else c
                                        for c in cmd))
    try:
        proc = subprocess.Popen(cmd, cwd=cwd)
        proc.communicate()
        return proc.returncode
    except FileNotFoundError:
        return -1


def derive_std_modules(gen_c_path):
    """从生成 C 的 #include "mod/xxx.h" 自动推导 std 模块，与显式基线取并集"""
    modules = set(BASE_STD_MODULES)
    try:
        with open(gen_c_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        for mod in re.findall(r'#include\s+"([A-Za-z0-9_]+)/', text):
            modules.add(mod)
    except OSError as e:
        print('[build_web] WARN: 无法读取生成 C 做模块推导，'
              '退回显式基线清单：%s' % e)
    modules -= FORBIDDEN_MODULES  # std.web/net 禁止进 WASM 链接
    modules.add('time')           # kaula.h 直接 include std/time/time.h，必链
    return sorted(modules)


def main():
    parser = argparse.ArgumentParser(
        description='Kaula WebUI WASM 构建（kaulac -> emcc）')
    parser.add_argument('source', help='入口 .kl 文件路径')
    parser.add_argument('-o', '--output-dir', default=None,
                        help='产物目录（默认 kaula-webui/dist/web/<入口名>）')
    parser.add_argument('--emcc', default=None, help='emcc.exe 路径覆盖')
    parser.add_argument('--skip-node-check', action='store_true',
                        help='跳过 node wasm 校验步骤')
    args = parser.parse_args()

    # ---------- 0. 路径解析与前置校验 ----------
    src_abs = os.path.abspath(args.source)
    if not os.path.isfile(src_abs):
        fail('入口文件不存在: %s' % src_abs)
    if not src_abs.lower().endswith('.kl'):
        fail('入口必须是 .kl 文件: %s' % src_abs)
    entry = os.path.splitext(os.path.basename(src_abs))[0]

    kaulac = os.path.join(COMPILER_DIR, 'kaulac.exe')
    if not os.path.isfile(kaulac):
        fail('kaulac.exe 不存在: %s' % kaulac)
    emcc = args.emcc or os.environ.get('EMCC') or DEFAULT_EMCC
    if not os.path.isfile(emcc):
        fail('emcc.exe 不存在: %s（可用 --emcc 指定）' % emcc)
    if not os.path.isfile(WASM_SHIM_C):
        fail('wasm_shim.c 不存在: %s' % WASM_SHIM_C)

    out_dir = os.path.abspath(args.output_dir) if args.output_dir \
        else os.path.join(WEBUI_DIR, 'dist', 'web', entry)
    os.makedirs(out_dir, exist_ok=True)

    print('[build_web] entry      = %s' % entry)
    print('[build_web] source     = %s' % src_abs)
    print('[build_web] output dir = %s' % out_dir)
    print('[build_web] emcc       = %s' % emcc)

    # ---------- 1. kaulac：.kl -> cache\<入口名>.c ----------
    gen_c = os.path.join(COMPILER_DIR, 'cache', entry + '.c')
    if os.path.isfile(gen_c):
        os.remove(gen_c)  # 清旧产物，确保校验的是本次生成
    # --cflags 携带 wasm_shim.c：native 验证链接需要 kw_shim_* 回退桩，
    # 否则 kaulac 以 undefined symbol 报 exit 1（但生成 C 仍会落盘）
    rc = run([kaulac, '--no-cache', '--cflags', WASM_SHIM_C, src_abs],
             cwd=COMPILER_DIR)
    if rc != 0:
        # 容忍 native 验证链接失败：只要生成 C 已落盘即可继续 emcc 链接
        if os.path.isfile(gen_c):
            print('[build_web] WARN: kaulac native 验证链接失败 '
                  '(exit %d)，但生成 C 已落盘，继续 emcc 链接' % rc)
        else:
            fail('kaulac 编译失败 (exit %d)' % rc)
    if not os.path.isfile(gen_c):
        fail('kaulac 报告成功但生成 C 不存在: %s' % gen_c)
    print('[build_web] 生成 C    = %s' % gen_c)

    # ---------- 2. std 模块清单 ----------
    modules = derive_std_modules(gen_c)
    std_c_files = []
    for mod in modules:
        mod_dir = os.path.join(KAULA_STD_DIR, mod)
        if not os.path.isdir(mod_dir):
            fail('std 模块目录不存在: %s（请检查 BASE_STD_MODULES/推导结果）'
                 % mod_dir)
        cs = sorted(f for f in os.listdir(mod_dir) if f.endswith('.c'))
        if not cs:
            fail('std 模块 %s 目录下没有 .c 文件' % mod)
        std_c_files.extend(os.path.join(mod_dir, f) for f in cs)
    print('[build_web] std 模块  = %s' % ', '.join(modules))

    # ---------- 3. emcc 链接 ----------
    cmd = [emcc]
    cmd.append(gen_c)                       # 生成的 Kaula C
    cmd.append(WASM_SHIM_C)                 # WASM 后端 C 垫片（EM_JS 桥）
    cmd.extend(os.path.join(KAULA_SRC_DIR, f) for f in RUNTIME_SRC_FILES)
    cmd.extend(std_c_files)
    cmd.extend(['-I', KAULA_SRC_DIR, '-I', KAULA_STD_DIR])
    cmd.append('-sEXPORTED_FUNCTIONS=' + ','.join(EXPORTED_FUNCTIONS))
    cmd.append('-sEXPORTED_RUNTIME_METHODS=' + ','.join(EXPORTED_RUNTIME_METHODS))
    cmd.append('-sALLOW_MEMORY_GROWTH')     # 必需：kmm_v4 mmap 依赖堆增长
    out_html = os.path.join(out_dir, entry + '.html')
    cmd.extend(['-o', out_html])

    rc = run(cmd, cwd=COMPILER_DIR)
    if rc != 0:
        fail('emcc 链接失败 (exit %d)' % rc)

    # ---------- 4. 产物校验 ----------
    artifacts = {
        'html': out_html,
        'js': os.path.join(out_dir, entry + '.js'),
        'wasm': os.path.join(out_dir, entry + '.wasm'),
    }
    print('[build_web] ---- 产物 ----')
    for kind, path in artifacts.items():
        if not os.path.isfile(path):
            fail('emcc 报告成功但产物缺失: %s' % path)
        print('[build_web]   %-4s %8s  %s'
              % (kind, human_size(os.path.getsize(path)), path))

    # ---------- 5. node 快速校验 wasm 可加载 ----------
    if not args.skip_node_check:
        node = shutil.which('node') or EMSDK_NODE
        js = ('const fs=require("fs");'
              'const p=process.argv[process.argv.length-1];'
              'const b=fs.readFileSync(p);'
              'WebAssembly.compile(b).then('
              '()=>{console.log("wasm validate OK ("+b.length+" bytes)");},'
              'e=>{console.error("wasm validate FAILED: "+e);process.exit(1);});')
        if node and os.path.isfile(node) or shutil.which('node'):
            rc = run([node, '-e', js, artifacts['wasm']], cwd=out_dir)
            if rc != 0:
                fail('node wasm 校验失败 (exit %d)' % rc)
        else:
            print('[build_web] WARN: 未找到 node，跳过 wasm 校验')

    print('[build_web] SUCCESS -> %s' % out_html)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        fail('用户中断')
