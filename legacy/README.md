# Legacy — 旧 SSR HTTP 方案存档

本目录是 Kaula WebUI 的**旧方案**存档，已被根目录的双端同构框架（native webview + 浏览器 WASM）完全取代，**仅供存档参考，勿用于新项目**。

## 旧方案是什么

`webui_all.kl`（单文件，约 677 行）是一个 server-side rendering（SSR）WebUI 框架：

- **运行模型**：`std.web` 起 HTTP 服务器（`http://localhost:8768`），框架在服务端拼 HTML 字符串、按 GET/POST 路由响应；浏览器只是展示端，交互依赖表单提交/页面刷新。
- **组件模型**：`Elem` / `Card` / `Navbar` / `Footer` / `Page`，`render()` 返回 HTML；程序化 `Style` API + CSS 工具类。
- **附带能力**：URL-encoded 表单解析与校验、单行 CORS、响应式网格。
- `webui_all.exe` 为该方案的编译产物。

## 为什么被取代

SSR 模型的交互回环走 HTTP 往返，无法承载实时双向 UI；新方案改为「纯 Kaula 应用 + 元素树 + 事件桥」，同一份应用代码经 webview 后端跑桌面窗口、经 WASM 后端跑浏览器，详见根目录 `README.md` 与 `docs/architecture.md`。旧方案中元素/样式 API 的设计（Elem/Style、键值样式构建器）被新框架核心 `webui/element.kl` 重构复用。

## 历史

文件经 `git mv` 迁入本目录，完整演进历史可通过 git log 追溯（`git log --follow legacy/webui_all.kl`）。
