"""The app's skin, shared by every server-rendered interactive page.

One source for the design tokens (mirrored from the served page's own
[data-skin]/[data-theme] blocks and mobile.css's Titans set) and for the
theme boot script that reads the page's `ww_theme` localStorage before
first paint -- so /app/mock, /login and /app/access all open in whatever
mode the app itself is in.
"""

from __future__ import annotations

TOKENS_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800;900&display=swap');
:root {
  --color-bg: oklch(0.955 0.025 90); --color-text: oklch(0.25 0.06 260);
  --color-neutral-200: oklch(0.92 0.025 90); --color-neutral-300: oklch(0.86 0.025 90);
  --color-neutral-400: oklch(0.72 0.03 95); --color-neutral-600: oklch(0.5 0.05 255);
  --color-neutral-700: oklch(0.42 0.06 258); --color-neutral-800: oklch(0.32 0.06 260);
  --color-accent: #b22234; --color-accent-100: oklch(0.92 0.03 20);
  --color-accent-200: oklch(0.85 0.06 20); --color-accent-400: oklch(0.55 0.15 20);
  --color-accent-700: oklch(0.44 0.15 18); --color-accent-800: oklch(0.35 0.12 18);
}
:root[data-theme="cowboys"] {
  --color-bg: oklch(0.14 0.015 260); --color-text: oklch(0.95 0.01 90);
  --color-neutral-200: oklch(0.18 0.008 260); --color-neutral-300: oklch(0.24 0.01 260);
  --color-neutral-400: oklch(0.4 0.015 260); --color-neutral-600: oklch(0.66 0.015 255);
  --color-neutral-700: oklch(0.75 0.012 250); --color-neutral-800: oklch(0.86 0.008 220);
  --color-accent: oklch(0.62 0.16 20); --color-accent-100: oklch(0.26 0.06 20);
  --color-accent-200: oklch(0.33 0.09 20); --color-accent-400: oklch(0.55 0.14 20);
  --color-accent-700: oklch(0.74 0.14 20); --color-accent-800: oklch(0.84 0.1 22);
}
:root[data-theme="titans"] {
  --color-bg: oklch(0.17 0.04 255); --color-text: oklch(0.94 0.008 240);
  --color-neutral-200: oklch(0.21 0.035 255); --color-neutral-300: oklch(0.26 0.04 255);
  --color-neutral-400: oklch(0.42 0.045 252); --color-neutral-600: oklch(0.66 0.04 248);
  --color-neutral-700: oklch(0.75 0.035 245); --color-neutral-800: oklch(0.86 0.02 240);
  --color-accent: oklch(0.68 0.12 245); --color-accent-100: oklch(0.27 0.06 250);
  --color-accent-200: oklch(0.34 0.08 248); --color-accent-400: oklch(0.56 0.11 246);
  --color-accent-700: oklch(0.76 0.11 242); --color-accent-800: oklch(0.85 0.08 240);
}
:root[data-theme="dark"] {
  --color-bg: #000; --color-text: oklch(0.95 0.01 90);
  --color-neutral-200: oklch(0.18 0.008 260); --color-neutral-300: oklch(0.24 0.01 260);
  --color-neutral-400: oklch(0.4 0.015 260); --color-neutral-600: oklch(0.66 0.015 255);
  --color-neutral-700: oklch(0.75 0.012 250); --color-neutral-800: oklch(0.86 0.008 220);
  --color-accent: oklch(0.62 0.16 20); --color-accent-100: oklch(0.26 0.06 20);
  --color-accent-200: oklch(0.33 0.09 20); --color-accent-400: oklch(0.55 0.14 20);
  --color-accent-700: oklch(0.74 0.14 20); --color-accent-800: oklch(0.84 0.1 22);
}
* { box-sizing: border-box; }
body { font-family: 'Archivo', system-ui, sans-serif; margin: 18px;
       color: var(--color-text); background: var(--color-bg);
       font-size: 14px; line-height: 1.45; }
"""

# Applied before first paint so pages never flash the wrong mode; same key
# and same accepted values as the served page (plus titans, which the
# serve-time patch adds there).
THEME_BOOT = (
    "<script>try{var t=localStorage.getItem('ww_theme');"
    "if(['dark','cowboys','titans'].indexOf(t)>=0)"
    "document.documentElement.dataset.theme=t;}catch(e){}</script>"
)


# Every page this app serves points at the same icon. SVG favicons are
# supported everywhere the rest of this app needs (Safari 15+, Firefox,
# Chromium); the apple-touch-icon line is what an iOS home-screen tile
# reads, and it is deliberately the same file rather than a second
# rendering that could drift from it.
FAVICON = (
    "<link rel='icon' type='image/svg+xml' href='/app/assets/fsb-icon.svg'>"
    "<link rel='apple-touch-icon' href='/app/assets/fsb-icon.svg'>"
    "<meta name='theme-color' content='#0B1A36'>"
)
