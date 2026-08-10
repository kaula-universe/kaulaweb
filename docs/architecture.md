# Kaula WebUI 架构与桥协议

本文档描述双端同构框架的分层结构、事件/渲染桥协议与两端的实现链路。用户视角的 API 用法见 [../README.md](../README.md)。

## 1. 分层

```
用户应用（纯 Kaula：状态全局、事件 handler、view 函数）
        ↓ 唯一入口 API（kw_* / app_set_render / bridge_refresh）
框架核心 webui/（纯 Kaula，平台无关，只 import WASM 安全 std 模块）
  element.kl   元素树 Elem/Style（句柄式 kw_* API，事件标注 data-kid）
  app.kl       生命周期、全局事件注册表（kid -> handler）、渲染回调
  bridge.kl    统一桥协议：kw_event(json) 收 / kw_render 发、Platform 抽象
  shell.kl     内置 JS 胶水（字符串常量）：事件采集 -> kaula_event()、
               kw_render(html) 替换 #app + 焦点/滚动恢复
        ↓ Platform 接口（show_html / eval_js，后端以函数指针注册）
backends/backend_webview.kl        backends/backend_wasm.kl + wasm_shim.c
（import webview C API，WebView2） （导出 kw_* 供 JS 直调，无桥序列化开销）
```

要点：

- 核心 `webui/` 只允许 import `std.string / std.json / std.container / std.memory / std.format` 等 WASM 安全模块；`std.web / std.net` 仅 native 后端可用，严禁进入核心。
- 用户应用不接触 HTML/JS/CSS；同一份逻辑文件（如 `examples/counter.kl`）被 native 与 web 两个薄入口复用。

## 2. 桥协议

### 2.1 上行（JS → Kaula）

shell.kl 的 JS 胶水在 document 上委托监听 `click/input/change/submit`（捕获阶段），向上查找最近的 `[data-kid]` 元素，组装事件 JSON 经 `window.kaula_event(json)` 发送：

```json
{"kid":"3","type":"input","value":"abc"}
```

- `kid`：渲染时由 `kw_on` 分配并输出为元素的 `data-kid` 属性，是注册表主键；每次全量重渲染会清空注册表并重新注册，保证 kid 与当前 DOM 一致。
- `type`：事件类型；form 提交被拦截（preventDefault）后作为 `submit` 事件发送，value 为 `name=value&…` 拼接。
- `seq` 为协议预留字段（当前 shell 未发送）。
- 两端统一入口均为 `kw_event(cstring json)`（bridge.kl）：手写最小 JSON 扫描提取字段（std.json 缺取值 API）→ `kw_dispatch_event` 查注册表 → 调 handler。

### 2.2 下行（Kaula → JS）

渲染管线（bridge.kl `kw_send`）区分首帧与后续帧：

- **首帧**：`kw_page(inner)` 组装完整页面（基础 CSS + `#app` 容器 + 内联 shell.js）→ `bridge_show_html` → 后端整页下发（native：`webview_set_html`；wasm：`document.write`）。
- **后续帧**：`bridge_eval_js("kw_render(\"<转义后的 #app 内容>\")")`。`kw_js_quote` 采用两遍扫描 + 一次定长分配（O(n)，见 bridge.kl 注释），把 HTML 包成合法单行 JS 字符串字面量；JS 侧 `kw_render` 保存焦点元素 data-kid / 光标位置 / 滚动位置 → 替换 `#app.innerHTML` → 恢复焦点与滚动。

shell.js 只随首帧内联一次；native 后端的 `webview_init` 仅承载附加脚本（如自动测试），重复注入会导致监听器注册两次、事件重复上报（见 backend_webview.kl 头注释）。

## 3. Native 事件链路（backend_webview.kl）

```
DOM 事件 -> shell.js -> window.kaula_event(json)
  -> webview_bind 注册的 kaula_event 回调（webview_run 主线程消息泵中执行）
     1) 立即 string_create 拷贝 payload（C 侧缓冲仅回调期间有效；
        边界函数标 #[no_kmm]，避开 KMM 托管）
     2) 解包 webview 的 JSON 数组包装（取第一元素，含反转义）
     3) 入固定容量环形队列（KW_EVQ_CAP=16，满则丢最旧）
     4) 回调返回前排空队列：kw_event -> 注册表分发 -> handler
        -> bridge_refresh -> webview_eval 下发新帧
```

实测结论（probe/wv_smoke）：回调在消息泵内执行，回调中可安全 `webview_eval / webview_return`，故 v1 无需 `webview_dispatch` 跨线程调度；环形队列把「解包/拷贝」与「协议分发」解耦，并为将来 worker 线程回调 + dispatch 留出口子。

webview 调用顺序硬约束：`create -> set_title/set_size -> bind -> init -> set_html -> run`（bind/init 必须早于 set_html，否则注入静默失效），由 `webview_backend_start` 统一保证。

## 4. WASM 链路（backend_wasm.kl + wasm_shim.c）

整个 Kaula 程序编译成 WASM 跑在浏览器里，shell.js 胶水在同一页面，事件**直调**无桥序列化：

```
下行（渲染）：
  bridge_show_html -> kw_shim_show_html（EMSCRIPTEN_KEEPALIVE 导出，
                     EM_JS 实现 document.write 首帧）
  bridge_eval_js   -> kw_shim_eval（EM_JS eval 执行 kw_render("...")）
上行（事件）：
  shell.js -> window.kaula_event(js_str)
    -> _malloc + stringToUTF8 编码进 wasm 堆
    -> _kw_shim_event(ptr)（导出）-> kw_event(Kaula，无 mangling)
```

时序要点：`kw_shim_install_event_bridge()`（EM_JS 安装 `window.kaula_event`，幂等）必须在首帧 `document.write` **之前**调用——页面被重写后内嵌 shell 胶水立即执行，`kaula_event` 必须在场；`wasm_backend_start()` 已保证该顺序。

运行模型：`main` 初始化完成（注册平台函数 + `kw_start` 下发首帧）后即返回，严禁阻塞循环，后续全部由浏览器事件驱动。

构建侧验证结论（wasm_shim.c 头注释）：kmm_v4 的 mmap 路径在 Emscripten 下需 `-sALLOW_MEMORY_GROWTH`（否则默认 16MB 线性内存 OOM abort）；禁止链接 `kaula\src\queue.c`（与 container.c 符号重复）。

## 5. FFI 约定（Kaula 语言约束的应对）

以下约定贯穿核心与双后端，源自 Kaula 编译器的实测限制：

- **函数指针以 `cstring` 承载传递**：`as<cstring>(函数名)`。因 `void()` 类型不能作参数/返回类型，别名类型也不能出现在函数签名（C 前置声明早于 typedef）；接收方再 `as<目标别名>(参数)` 转回。
- **回调必须是无捕获具名函数**：带捕获 lambda 不能作 C 回调（见 kaula/docs/semantic-analysis.md），故采用「具名 handler + 全局注册表（kid → handler）」模式；应用状态由用户以全局变量自管。
- **别名中字符串参数必须是 `cstring`**：编译器把别名里的 `string` 映射为 `char*`，与 Kaula 的 String 结构体 ABI 不匹配；需要 String 时传 `.ptr`，长期持有须在回调内 `string_create` 拷贝。
- **extern 声明放文件末尾**：extern fn 返回类型解析会贪婪吞掉后续类型行（probe/wv_smoke.kl 实测）。
- **局部声明提升到函数顶层**：块内（if/while 体）声明局部变量会触发 KMM 作用域回卷，块内分配的字符串缓冲被卷入可复用区，块外持有的结果悬垂被覆盖——element.kl 渲染、app.kl 分发、bridge.kl 下发的关键缓冲均已提升。

## 6. 渲染策略

- **v1：整页重渲染**。每次 `bridge_refresh` 全量重建元素树 → 渲染 HTML → `kw_render` 替换 `#app.innerHTML`；JS 胶水负责保存并恢复焦点元素（data-kid + 光标位置）与滚动位置，避免输入失焦。实现简单、协议稳定，适合当前应用规模。
- **keyed 增量预留位**：元素树按 keyed 属性（data-kid）预留增量 diff 升级位——升级只替换「替换 innerHTML」这一步为 diff patch，桥协议（`kw_event`/`kw_render`）与上层 API（`kw_*`/`bridge_refresh`）均不变。
- 注册表容量上限 `KW_MAX_KID = 1024`，超限绑定丢弃并落盘 `kw_error.log`。
