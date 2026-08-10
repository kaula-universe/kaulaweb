/* ============================================================
 * wasm_shim.c — Kaula WebUI WASM 后端 C 垫片（Emscripten）
 * ------------------------------------------------------------
 * 职责：Kaula(wasm) <-> 浏览器 DOM 的双向桥
 *   下行（渲染）：
 *     kw_shim_show_html  首帧整页 HTML -> document.write
 *     kw_shim_eval       后续帧 JS（kw_render("...")）-> eval
 *     kw_shim_inject_shell  追加 <script> 到 head（防御性备用；
 *                           核心 kw_page 已内嵌 shell 胶水，通常无需调用）
 *   上行（事件）：
 *     window.kaula_event(js_str)  --shell.kl 胶水的发送点-->
 *     _malloc+stringToUTF8 编码 -> _kw_shim_event(ptr) -> kw_event(Kaula)
 *
 * 符号确认：Kaula 生成的 C 中 kw_event 无 mangling，即
 *     KAULA_EXPORT void kw_event(const char* json);
 *   （见 kaula-compiler/cache/core_selftest.c）
 *
 * 时序要点：kw_shim_install_event_bridge() 必须在首帧
 *   kw_shim_show_html 的 document.write 之前调用——页面被重写后
 *   内嵌 shell 胶水立即执行，window 上的 kaula_event 必须在场。
 *   Kaula 侧 wasm_backend_start() 已保证该顺序；垫片内部亦幂等兜底。
 *
 * #10 构建脚本 emcc 参考命令（已在 emcc 6.0.6 验证通过；在 kaula\kaula-compiler
 * 目录下执行，kaulac --no-cache 生成的 C 落在该目录 cache\ 下，文件名取主入口名）：
 *   emcc cache\backend_wasm.c ..\..\kaula-webui\backends\wasm_shim.c ^
 *        ..\src\kmm_scoped_allocator_v4.c ..\src\spend_call.c ..\src\allocator.c ^
 *        ..\std\io\io.c ..\std\string\string.c ^
 *        ..\std\container\container.c ..\std\container\container_ext.c ^
 *        ..\std\time\time.c ^
 *        -I ..\src -I ..\std ^
 *        -sEXPORTED_FUNCTIONS=_main,_kw_shim_event,_kw_shim_show_html,_kw_shim_eval,_kw_shim_inject_shell,_kw_shim_install_event_bridge,_malloc,_free ^
 *        -sEXPORTED_RUNTIME_METHODS=UTF8ToString,stringToUTF8,lengthBytesUTF8 ^
 *        -sALLOW_MEMORY_GROWTH -o app.html
 *
 * 验证结论（2026-08-10）：
 *   - kmm_v4 的 mmap 路径在 Emscripten 下可编译且可运行（mmap 被
 *     emscripten 仿真为堆增长），但必须加 -sALLOW_MEMORY_GROWTH，
 *     否则默认 16MB 线性内存不足会 OOM abort。
 *   - 禁止链接 kaula\src\queue.c：priority_queue_create/destroy 与
 *     std\container\container.c 重复定义（wasm-ld duplicate symbol）。
 *   - core_selftest 的 wasm 产物在 node(-sNODERAWFS) 下运行 ALL-PASS。
 *
 * 非 Emscripten（native）编译：提供 printf 回退桩，仅用于
 *   kaulac 侧链接验证，产物不运行。
 * ============================================================ */

#include <stdio.h>
#include <stddef.h>
#include <string.h>

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <emscripten/em_js.h>

/* ---------- Kaula 侧事件入口（backend_wasm.kl 生成 C 中定义） ---------- */
extern void kw_event(const char* json);

/* ---------- 事件桥安装 ----------
 * window.kaula_event(s: JS string) -> 编码到 wasm 堆 -> _kw_shim_event(ptr)
 * 注意方向：JS 字符串进 wasm 需 stringToUTF8（UTF8ToString 是反向的
 * wasm->JS 解码，勿混用）。幂等，重复调用只装一次。
 */
EM_JS(void, kw_shim_install_event_bridge_js, (void), {
    if (window.__kaula_bridge_installed) { return; }
    window.__kaula_bridge_installed = true;
    window.kaula_event = function (s) {
        try {
            var m = (typeof Module !== 'undefined') ? Module : null;
            if (!m || !m._kw_shim_event) { return; }
            var len = lengthBytesUTF8(s) + 1;
            var buf = _malloc(len);
            /* wasm 堆分配失败（返回 0）：丢弃本事件，避免向地址 0 写入 */
            if (!buf) { return; }
            stringToUTF8(s, buf, len);
            m._kw_shim_event(buf);
            _free(buf);
        } catch (e) {
            console.error('[kaula-wasm] kaula_event bridge error:', e);
        }
    };
});

void kw_shim_install_event_bridge(void) {
    kw_shim_install_event_bridge_js();
}

/* ---------- 上行：JS -> Kaula ----------
 * EMSCRIPTEN_KEEPALIVE 保证不被 wasm-ld 死代码消除，导出为 _kw_shim_event。
 * 入参为 kaula_event 已编码好的 UTF-8 指针（见上）。
 */
EMSCRIPTEN_KEEPALIVE
void kw_shim_event(const char* json) {
    if (json == NULL) {
        return;
    }
    kw_event(json);
}

/* ---------- 下行：整页 HTML（首帧） ----------
 * 先兜底安装事件桥（幂等），再 document.open/write/close 重写整页。
 * window 对象在 document.write 后保留，kaula_event 随之存活。
 */
EM_JS(void, kw_shim_show_html_js, (const char* html), {
    kw_shim_install_event_bridge_js();
    document.open();
    document.write(UTF8ToString(html));
    document.close();
});

EMSCRIPTEN_KEEPALIVE
void kw_shim_show_html(const char* html) {
    if (html == NULL) {
        return;
    }
    kw_shim_show_html_js(html);
}

/* ---------- 下行：执行 JS（后续帧 kw_render(...) / 任意脚本） ---------- */
EM_JS(void, kw_shim_eval_js, (const char* js), {
    try {
        (0, eval)(UTF8ToString(js));
    } catch (e) {
        console.error('[kaula-wasm] eval error:', e);
    }
});

EMSCRIPTEN_KEEPALIVE
void kw_shim_eval(const char* js) {
    if (js == NULL) {
        return;
    }
    kw_shim_eval_js(js);
}

/* ---------- 备用：注入 shell 脚本（kw_page 已内嵌，一般无需） ---------- */
EM_JS(void, kw_shim_inject_shell_js, (const char* js), {
    var s = document.createElement('script');
    s.textContent = UTF8ToString(js);
    document.head.appendChild(s);
});

EMSCRIPTEN_KEEPALIVE
void kw_shim_inject_shell(const char* js) {
    if (js == NULL) {
        return;
    }
    kw_shim_inject_shell_js(js);
}

#else /* ============ native 回退桩（仅 kaulac 链接验证） ============ */

void kw_shim_install_event_bridge(void) {
    printf("[wasm_shim][native-stub] install_event_bridge\n");
}

void kw_shim_event(const char* json) {
    printf("[wasm_shim][native-stub] event: %s\n", json ? json : "(null)");
}

void kw_shim_show_html(const char* html) {
    printf("[wasm_shim][native-stub] show_html: %zu bytes\n",
           html ? strlen(html) : 0);
}

void kw_shim_eval(const char* js) {
    printf("[wasm_shim][native-stub] eval: %s\n", js ? js : "(null)");
}

void kw_shim_inject_shell(const char* js) {
    printf("[wasm_shim][native-stub] inject_shell: %zu bytes\n",
           js ? strlen(js) : 0);
}

#endif /* __EMSCRIPTEN__ */
