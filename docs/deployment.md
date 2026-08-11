# Kaula WebUI 部署指南

本文档说明：用本框架构建的应用如何部署到两个端——**native 桌面**（webview 后端）与**浏览器**（WASM 后端），以及部署前的环境要求。架构与桥协议见 [architecture.md](architecture.md)，API 用法见 [../README.md](../README.md)。

核心事实先说清：

- **构建机**（你开发/编译的机器）需要完整工具链；**目标机**要求极低——native 端只需 Windows + WebView2 Runtime，web 端只需一个现代浏览器。
- 两端产物均为**自包含**：native 是单个 exe；web 是 html/js/wasm 三件套纯静态文件，无需任何后端服务。

## 1. 环境要求

### 1.1 构建机（两端共用）

| 组件 | 用途 | 说明 |
|------|------|------|
| Windows（x64）+ python | 构建脚本运行环境 | 构建脚本已统一为 Python 版（`build\build_native.py` / `build\build_web.py`），任意现代 Python 版本即可，不再依赖 PowerShell |
| `kaulac.exe` | Kaula 编译器 | 须位于 `..\kaula\kaula-compiler\`（相对 `kaula-webui\` 的路径关系由 `build\build_native.py` 的 `default_compiler_dir()` 定位逻辑约定；脚本自动切到该目录调用，勿移动） |
| clang | native 链路的 C 编译（kaulac 转译 .kl → C → clang） | kaulac 先在 PATH 中查找 `clang`，再回退常见安装路径（`D:\LLVM\bin\clang.exe`、`C:\LLVM\bin\clang.exe`、`C:\Program Files\LLVM\bin\clang.exe`） |
| python | `build\build_native.py`（native 构建）与 `build\build_web.py`（WASM 构建主体） | 任意现代版本 |
| node | WASM 产物的加载校验 | 不在 PATH 时脚本自动回退 emsdk 内置 node（`tools\emsdk\node\24.19.0_64bit\node.exe`），故**可不单独安装** |
| `tools\emsdk`（emcc） | WASM 链接 | 脚本内置绝对路径 `tools\emsdk\upstream\emscripten\emcc.exe`，**无需加入 PATH、无需手动激活**；如需覆盖可用 `--emcc` 参数或 `EMCC` 环境变量 |

### 1.2 Native 目标机

- Windows（x64）；
- **WebView2 Runtime**：Windows 10/11 随 Edge 预装；缺失时应用不会崩溃，后端会输出提示（见 §4 常见问题），安装 Microsoft Edge WebView2 Runtime 即可。

### 1.3 Web 目标机

- 只需现代浏览器（支持 WebAssembly 与 `fetch`）。无需安装任何东西，无需服务器端运行时。

## 2. Native 部署（桌面窗口）

### 2.1 构建

```powershell
# kaula-webui\build\ 下执行
python build_native.py ..\examples\counter_native.kl            # 产物归集 dist\native\
python build_native.py ..\examples\todo_native.kl -o D:\release
```

- 参数：`<入口 .kl>`（必填）；`-o/--output-dir <目录>`（可选，默认 `kaula-webui\dist\native\`）。
- 脚本默认附加 `--no-cache`（规避增量缓存对 import 变更失效的问题）；编译在 `kaula\kaula-compiler` 目录下完成，产物随后移动归集到输出目录（kaulac 的 `-output-dir` 旗标实测不生效，故用后置归集，见脚本头注释）。

### 2.2 分发

产物是**单个 exe，自包含**：`libwebview.a` 在编译期静态链接，Kaula 运行时与 std 模块同样静态进产物，**无须随附任何 dll / 资源文件**。部署即拷贝这一个文件。

唯一的外部依赖是目标机系统级的 WebView2 Runtime（§1.2）。

### 2.3 运行与日志

- 直接双击/命令行运行 exe 即弹出窗口，无参数、无配置文件；关闭窗口进程退出。
- 日志按**进程当前工作目录**落盘（append 模式）：
  - `kw_backend.log` —— 后端关键节点（create/bind/init/set_html、WebView2 缺失的 FATAL 提示）；
  - 业务侧日志由入口程序决定（如 examples 的 `counter_native.log` / `todo_native.log`）。
- GUI 进程的 stdout 不可靠（框架设计如此），排障一律看上述日志文件。

### 2.4 多机器部署注意

- 同架构 Windows x64 之间直接拷贝 exe 即可（本机实测环境即 Windows x64）；
- 建议以固定工作目录启动（如快捷方式的"起始位置"），便于集中收集日志；
- 目标机首启若窗口未出现，先查工作目录下 `kw_backend.log` 是否记录 WebView2 缺失。

## 3. Web / WASM 部署（浏览器）

### 3.1 构建

```powershell
# kaula-webui\build\ 下执行（任意工作目录均可）
python build_web.py ..\examples\counter_web.kl                    # 默认产物 dist\web\counter_web\
python build_web.py ..\examples\todo_web.kl -o ..\dist\web\todo_web
```

- 参数：`<入口 .kl>`（必填）；`-o/--output-dir`（默认 `kaula-webui\dist\web\<入口名>\`）；`--emcc`（覆盖 emcc 路径）；`--skip-node-check`（跳过 wasm 加载校验）。
- 流程：`kaulac --no-cache` 生成 C → 自动推导 std 模块 → emcc 链接（强制 `-sALLOW_MEMORY_GROWTH`）→ 产物齐全校验 → node 验证 wasm 可加载。

产物为三件套，**纯静态**：

```
dist\web\<name>\
├── <name>.html    # 页面（emcc shell）
├── <name>.js      # Emscripten 胶水（加载 wasm、导出桥函数）
└── <name>.wasm    # 整个 Kaula 程序
```

**多页面/多应用**：每个入口独立构建、产物落在并列目录（如 `dist\web\counter_web\` 与 `dist\web\todo_web\`），互不共享文件，各自独立部署即可。

### 3.2 托管

产物无后端、无动态接口，任意静态托管均可。本地验证：

```powershell
python -m http.server 8123 -d ..\dist\web\counter_web
# 浏览器打开 http://localhost:8123/counter_web.html
```

常见托管平台要点：

| 平台 | 要点 |
|------|------|
| Vercel | 静态部署即可（output 目录指向产物目录）；无构建命令需求 |
| GitHub Pages | 把产物目录作为站点根或子目录发布；注意 Pages 的 404 兜底与路径前缀 |
| Nginx | 静态站点配置即可；建议确认/添加 `.wasm` 的 MIME：`types { application/wasm wasm; }`（新版 nginx 的 mime.types 已内置）；并对三件套开启 gzip 压缩（`.wasm`/`.js` 压缩收益显著） |

通用建议：

- `.wasm` 的 Content-Type 应为 `application/wasm`（托管层 MIME 配错时浏览器可能拒绝以流式方式编译，甚至加载失败）；
- 建议开启 gzip/brotli 压缩——`.wasm` 与 `.js` 体积压缩收益大；
- 无需后端、无需 CORS 特殊配置（同目录同源加载）。

### 3.3 访问方式限制

**必须经 HTTP(S) 访问，不要双击 `file://` 打开**：Emscripten 生成的 JS 通过 `fetch` 加载 `.wasm`，浏览器对 `file://` 协议的跨源请求一律拒绝（Chrome/Edge/Firefox 均如此）。本地预览请用 §3.2 的 `python -m http.server` 或任意静态服务器。

## 4. 常见问题

- **改了核心 .kl，产物却像没更新？** kaulac 增量缓存对 import 变更可能失效。两个构建脚本均已默认 `--no-cache`，正常走脚本不会遇到；仅当你绕过脚本手工调 `kaulac` 时，请自行附加 `--no-cache`。
- **中文路径编译报错？** 已规避：`build_native.py` 解析绝对路径后转相对路径、并在编译器目录下执行；`build_web.py` 同样以绝对路径推导并自行切 cwd。请尽量经脚本构建而非手工拼命令。
- **native 窗口没弹出来？** 大概率缺 WebView2 Runtime。后端在 `webview_create` 失败时向控制台打印 `WebView2 Runtime missing?` 并落盘 `kw_backend.log`（`[backend][FATAL]` 行）。安装 Microsoft Edge WebView2 Runtime 后重试。
- **WASM 页双击 html 打不开 / 卡在加载？** `file://` 限制（§3.3），改用 HTTP 服务器访问。
- **WASM 构建报 duplicate symbol？** 不要链接 `kaula\src\queue.c`（与 `std\container\container.c` 符号重复）；也不要让 `std.web`/`std.net` 进入 WASM 链接。`build_web.py` 已内置这两条硬约束，手工 emcc 时注意（见该脚本头注释）。
