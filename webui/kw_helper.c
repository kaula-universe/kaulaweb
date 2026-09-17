#include <stdint.h>
#include <stddef.h>

/* Kaula String 类型定义（与 std/base/types.h 一致） */
typedef struct {
    size_t len;
    union {
        char* ptr;
        char sso[16];
    };
} String;

String kw_call_render(int64_t fn_ptr) {
    String (*fn)(void) = (String (*)(void))(void*)(uintptr_t)fn_ptr;
    return fn();
}

void kw_call_event(int64_t fn_ptr, String arg) {
    void (*fn)(String) = (void (*)(String))(void*)(uintptr_t)fn_ptr;
    fn(arg);
}
