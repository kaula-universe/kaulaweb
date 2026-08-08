# Kaula WebUI Framework

A server-side rendering WebUI framework written in Kaula, featuring:

- **Component model** — `Elem`, `Card`, `Navbar`, `Footer`, `Page` with `render()` returning HTML
- **Style builder** — Programmatic `Style` API + CSS utility classes (`.container`, `.grid`, `.card`, `.btn`, `.tag`, etc.)
- **Routing** — HTTP method + path matching (GET/POST) for pages, raw HTML, JSON endpoints
- **Forms** — URL-encoded body parsing with validators
- **CORS** — One-liner cross-origin support
- **Responsive** — Grid `cols-2`/`cols-3` collapse on mobile
- **Zero dependencies** — Only Kaula stdlib (`std.io`, `std.string`, `std.container`, `std.memory`, `std.web`)

## Two Flavors

| File | Description |
|------|-------------|
| `webui_all.kl` | **Single-file** framework (~677 lines) — copy-paste ready |
| `webui/` | **Modular** version split into `elements.kl`, `components.kl`, `styles.kl`, `app.kl` |

## Quick Start

```bash
# Compile single-file version
kaulac webui_all.kl -o webui
./webui
# Server runs at http://localhost:8768
```

Routes: `/` `/features` `/demo` `/contact` `/api/health` `/api/features`

## Modular Usage

```kaula
import webui.elements   // Elem, Style
import webui.components // Card, Navbar, Footer, Page
import webui.styles     // Default CSS
import webui.app        // Page builders + HTTP handler
```

## License

MIT