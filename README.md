# Kaula WebUI — 双端同构 UI 框架

用纯 Kaula 编写 UI 应用，**同一份应用代码**编译运行于两个目标：

| 端 | 后端 | 运行形态 |
|------|------|----------|
| Native | `backends/backend_webview.kl`（pkglib/webview FFI，WebView2） | 桌面窗口进程 |
| 浏览器 | `backends/backend_wasm.kl` + `backends/wasm_shim.c`（Emscripten） | WASM 静态页 |

用户只写纯 Kaula：`kw_*` 句柄 API 构建元素树、`kw_on` 绑定事件、`bridge_refresh` 触发重渲染——不接触 HTML/JS/CSS。架构细节见 [docs/architecture.md](docs/architecture.md)。

## 目录结构

```
kaula-webui/
├── webui/                        # 框架核心（纯 Kaula，平台无关）
│   ├── element.kl                #   元素树/样式：kw_* 句柄 API
│   ├── app.kl                    #   生命周期、事件注册表（kid -> handler）、渲染回调
│   ├── bridge.kl                 #   桥协议：kw_event 收 / kw_render 发、Platform 抽象
│   └── shell.kl                  #   内置 JS 胶水（事件采集 + 焦点/滚动恢复）
├── backends/
│   ├── backend_webview.kl        # native 后端（import webview C API）
│   ├── backend_wasm.kl           # WASM 后端（导出 kw_* 供 JS 直调）
│   └── wasm_shim.c               # WASM 后端 C 垫片（EM_JS 桥接 DOM）
├── examples/
│   ├── counter.kl, todo.kl       # 应用逻辑（平台无关，无 main）
│   ├── counter_native.kl, todo_native.kl   # native 薄入口
│   └── counter_web.kl, todo_web.kl         # WASM 薄入口（复用同一份逻辑）
├── build/
│   ├── build_native.ps1          # native 构建（封装 kaulac）
│   ├── build_web.ps1 / build_web.py        # WASM 构建（kaulac -> emcc -> dist\web\）
├── probe/wv_smoke.kl             # webview FFI 冒烟探针
├── dist/native/                  # native 产物（build_native.ps1 归集的 .exe）
├── dist/web/<name>/              # WASM 产物（html/js/wasm）
├── docs/architecture.md          # 架构与桥协议文档
└── legacy/                       # 旧 SSR HTTP 方案存档（webui_all.kl，勿用于新项目）
```

## 构建

两个脚本的详细用法与注意事项见各自文件头注释。

### Native（webview 后端）

```powershell
# kaula-webui\build\ 下执行
.\build_native.ps1 ..\examples\counter_native.kl
```

脚本先切到 `kaula\kaula-compiler` 目录调用 `kaulac.exe`（cache/ 与 pkglib 相对配置的硬约束），默认附加 `--no-cache`，并在编译后把产物 `.exe` 归集到 **`dist\native\`**（kaulac 的 `-output-dir` 旗标实测不生效，故用后置 Move 归集；可用 `-OutputDir` 覆盖），保持 examples 源码目录整洁。

### Web（WASM 后端）

```powershell
# kaula-webui\build\ 下执行；任意工作目录均可
.\build_web.ps1 ..\examples\counter_web.kl -o ..\dist\web\counter_web
```

`build_web.ps1` 是 `build_web.py` 的 PowerShell 封装，行为完全一致：`kaulac --no-cache` 生成 C → 推导所需 std 模块 → emcc 链接 `wasm_shim.c` 与运行时 → 产物校验 → node 跑 wasm 校验。emcc 不在 PATH 亦可（内部用 `tools\emsdk` 绝对路径）。可选透传参数：`-o/--output-dir`、`--emcc`、`--skip-node-check`。

产物为静态页（`dist\web\<name>\<name>.html` 等），任意静态服务器打开即可，如：

```powershell
python -m http.server 8123 -d ..\dist\web\counter_web
```

## 用户 API 指南

### 元素 API（`webui/element.kl`）

句柄式 API：所有元素以 `int` 句柄表示（Kaula 编译器当前不支持跨文件 class，故对外只暴露顶层函数）。

| API | 说明 |
|-----|------|
| `kw_elem(tag)` / `kw_div()` / `kw_span()` / `kw_button(text)` / `kw_p(text)` / `kw_input(typ)` / `kw_form()` | 创建元素，返回句柄 |
| `kw_set_text(h, s)` / `kw_set_attr(h, raw)` | 文本 / 原始属性（如 `placeholder="hi"`） |
| `kw_set_style_str(h, css)` / `kw_set_style(h, style_handle)` | 内联样式 |
| `kw_style()` + `kw_sty_bg/color/pad/margin/rad/border/font_sz/…(h, v)` | 键值 Style 构建器 |
| `kw_add(parent, child)` | 挂接子节点（树形结构，非字符串拼接） |
| `kw_render_elem(h)` | 递归渲染为 HTML 字符串 |

事件绑定统一走 `app.kl` 的 `kw_on(h, event_type, handler)`（分配 `data-kid` 并登记注册表）。

### 生命周期 API（`webui/app.kl`）

- `app_set_render(as<cstring>(view))` —— 注册渲染回调。约定：`fn view() cstring`，把渲染结果存入**全局** string 后返回其 `.ptr`（框架立即拷贝）。
- `kw_on(h, "click"/"input"/"change"/"submit", as<cstring>(handler))` —— 绑定事件。handler 约定：`fn h(cstring payload) void`，payload 为事件 value 原文，长期持有须 `string_create` 拷贝。

### 桥 API（`webui/bridge.kl`）

- `kw_start()` —— 初始化框架（注册表 + 事件钩子）并渲染首帧。调用前须已完成 `app_set_render` 与后端的平台函数注册（native 为 `bridge_register`，wasm 为 `wasm_backend_start()` 内部完成）。
- `bridge_refresh()` —— 状态变更后调用：清空注册表 → 重新 render → 下发（首帧 `show_html`，后续 `eval kw_render(...)`）。

### 范例：counter 的 main 流程

应用逻辑（`examples/counter.kl`）只有三部分：状态全局、handler（改状态后 `bridge_refresh()`）、view（每帧重建元素树，返回 HTML 指针）。native 薄入口 `examples/counter_native.kl` 的 `main`：

```kaula
fn main() {
    counter_init()

    # 1) 注册渲染回调（view 返回全局缓冲的 .ptr，框架立即拷贝）
    app_set_render(as<cstring>(counter_view))
    # 2) 注册平台函数（show/eval 落到 webview 后端）
    bridge_register(as<cstring>(wv_show), as<cstring>(wv_eval))

    # 3) native：创建窗口（create/title/size/bind/init 顺序由后端保证）
    webview_backend_start("Kaula Counter", 480, 360)
    # 4) 渲染首帧 -> show_html -> webview_set_html
    kw_start()
    # 5) 阻塞主循环（窗口关闭后返回）
    webview_backend_run()
}
```

WASM 薄入口 `examples/counter_web.kl` 更短：`wasm_backend_start()` 注册浏览器平台函数后 `kw_start()` 下发首帧即返回（严禁阻塞循环），后续交互全部由浏览器事件经 `kaula_event -> shim -> kw_event` 驱动。

## 运行示例

```powershell
# native（产物归集在 dist\native\，直接运行）
.\build\build_native.ps1 .\examples\counter_native.kl
.\dist\native\counter_native.exe

.\build\build_native.ps1 .\examples\todo_native.kl
.\dist\native\todo_native.exe

# web（产物在 dist\web\<name>\，用静态服务器打开）
.\build\build_web.ps1 .\examples\counter_web.kl -o .\dist\web\counter_web
.\build\build_web.ps1 .\examples\todo_web.kl    -o .\dist\web\todo_web
```

## 已知注意事项

- **增量缓存陷阱**：`kaulac` 的增量缓存对 `import` 变更可能失效——修改 `webui\` / `backends\` 下的核心 `.kl` 后，务必使用 `--no-cache` 重新编译（`build_web.py` 默认即 `--no-cache`；native 手工编译时请自行附加），否则可能链到旧产物。
- **KMM 池为编译期静态估算**：全局池容量按 AST 静态估算（本项目实测 2MB），作用域回卷仅复用 thread heap。切勿写 O(n²) 逐字符字符串拼接——一帧 ~2KB 视图的逐字符 churn 即可耗尽池（`string_concat` 返回 NULL）。框架内 `bridge.kl` 的 `kw_js_quote` 已按「两遍扫描 + 一次定长分配」修复，参见其注释；用户代码同理：批量字符串请用两遍法或 `std.string.string_concat` 控制分配次数。
- **handler/局部变量约定**：事件 handler 必须是无捕获具名函数（Kaula 带捕获 lambda 不能作 C 回调）；应用状态以全局变量自管；函数指针一律以 `as<cstring>(函数名)` 传递。
- **webview 注入脚本长度**：`webview_init` 注入脚本实测超过约 512 字节会被截断（见 `backend_webview.kl` 与 `counter_native.kl` 注释）。

## License

MIT
