"""Shared light/dark CSS for the styled sprint HTML report.

Browser export uses CSS variables + ``prefers-color-scheme`` + a small toggle.
GUI preview (QTextBrowser) uses a resolved single-theme stylesheet because Qt's
rich-text engine does not reliably support CSS variables or media queries.
"""

from __future__ import annotations

# Product tokens (aligned with GUI / README assets)
LIGHT = {
    "page": "#F7F9FC",
    "surface": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
    "header": "#EEF3FA",
    "header_strong": "#F0F4FF",
    "border": "#D5DEEC",
    "accent": "#2176FF",
    "accent_text": "#0B3D91",
    "zebra": "#FAFBFC",
    "total": "#E8F0FF",
    "chip_bg": "#E8F0FF",
    "warn_bg": "#FFF7ED",
    "warn_text": "#B45309",
    "warn_strong": "#DC2626",
    "code_bg": "#F1F5F9",
    "blockquote_bg": "#F7FAFF",
}

DARK = {
    "page": "#0F172A",
    "surface": "#1E293B",
    "text": "#E2E8F0",
    "muted": "#94A3B8",
    "header": "#1E3A5F",
    "header_strong": "#1E3A5F",
    "border": "#334155",
    "accent": "#5A9BFF",
    "accent_text": "#93C5FD",
    "zebra": "#172033",
    "total": "#1E3A5F",
    "chip_bg": "#1E3A5F",
    "warn_bg": "#3B2F1A",
    "warn_text": "#FBBF24",
    "warn_strong": "#FCA5A5",
    "code_bg": "#0F172A",
    "blockquote_bg": "#172033",
}


def _rules(c: dict[str, str]) -> str:
    return f"""
  body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px;
    line-height: 1.45;
    color: {c['text']};
    background: {c['page']};
    margin: 0;
    padding: 20px 24px 40px 24px;
  }}
  a {{ color: {c['accent']}; }}
  .report-header {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 18px 20px;
    margin-bottom: 22px;
  }}
  .report-header h1 {{
    margin: 0 0 8px 0;
    font-size: 22px;
    color: {c['text']};
    border: 0;
    padding: 0;
  }}
  .meta {{ color: {c['muted']}; font-size: 13px; margin: 4px 0; }}
  .goal {{ color: {c['muted']}; font-size: 12px; margin-top: 8px; }}
  .chips {{ margin-top: 14px; }}
  .chip {{
    display: inline-block;
    background: {c['chip_bg']};
    color: {c['accent_text']};
    border: 1px solid {c['border']};
    border-radius: 999px;
    padding: 4px 12px;
    margin-right: 8px;
    margin-top: 4px;
    font-weight: 700;
    font-size: 12px;
  }}
  .theme-toggle {{
    float: right;
    font-size: 12px;
  }}
  .theme-toggle button {{
    background: {c['header']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px 10px;
    margin-left: 4px;
    cursor: pointer;
    font-size: 12px;
  }}
  h2 {{
    font-size: 16px;
    color: {c['accent']};
    margin: 28px 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 1px solid {c['border']};
  }}
  h3 {{
    font-size: 14px;
    color: {c['accent_text']};
    margin: 18px 0 8px 0;
  }}
  section {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 14px 16px 8px 16px;
    margin: 14px 0 18px 0;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0 12px 0;
    background: {c['surface']};
  }}
  th, td {{
    border: 1px solid {c['border']};
    padding: 6px 8px;
    vertical-align: top;
  }}
  th {{
    background: {c['header']};
    color: {c['accent_text']};
    text-align: left;
    font-weight: 700;
  }}
  td.num, th.num {{ text-align: right; }}
  tr:nth-child(even) td {{ background: {c['zebra']}; }}
  tr.total td {{
    background: {c['total']};
    font-weight: 700;
  }}
  tr.warn td {{ background: {c['warn_bg']}; }}
  tr.warn td.rem {{ color: {c['warn_strong']}; font-weight: 700; }}
  code {{
    background: {c['code_bg']};
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
  }}
  blockquote, .note {{
    border-left: 3px solid {c['accent']};
    margin: 8px 0 12px 0;
    padding: 6px 12px;
    background: {c['blockquote_bg']};
    color: {c['muted']};
  }}
  .empty {{ color: {c['muted']}; font-style: italic; margin: 8px 0; }}
  .muted {{ color: {c['muted']}; font-size: 12px; }}
  .chart-wrap {{ text-align: center; margin: 12px 0; }}
  .chart-wrap img {{ max-width: 100%; height: auto; border: 1px solid {c['border']}; border-radius: 8px; }}
  hr {{ border: 0; border-top: 1px solid {c['border']}; margin: 20px 0; }}
"""


def report_css_for_theme(theme: str) -> str:
    """Resolved CSS for a single theme (``light`` or ``dark``) — GUI-safe."""
    palette = DARK if theme == "dark" else LIGHT
    return f"<style>\n{_rules(palette)}\n</style>"


def report_css_browser() -> str:
    """Full dual-theme CSS for standalone HTML opened in a browser."""
    light = LIGHT
    dark = DARK
    return f"""<style>
:root {{
  --page: {light['page']};
  --surface: {light['surface']};
  --text: {light['text']};
  --muted: {light['muted']};
  --header: {light['header']};
  --border: {light['border']};
  --accent: {light['accent']};
  --accent-text: {light['accent_text']};
  --zebra: {light['zebra']};
  --total: {light['total']};
  --chip-bg: {light['chip_bg']};
  --warn-bg: {light['warn_bg']};
  --warn-text: {light['warn_text']};
  --warn-strong: {light['warn_strong']};
  --code-bg: {light['code_bg']};
  --blockquote-bg: {light['blockquote_bg']};
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --page: {dark['page']};
    --surface: {dark['surface']};
    --text: {dark['text']};
    --muted: {dark['muted']};
    --header: {dark['header']};
    --border: {dark['border']};
    --accent: {dark['accent']};
    --accent-text: {dark['accent_text']};
    --zebra: {dark['zebra']};
    --total: {dark['total']};
    --chip-bg: {dark['chip_bg']};
    --warn-bg: {dark['warn_bg']};
    --warn-text: {dark['warn_text']};
    --warn-strong: {dark['warn_strong']};
    --code-bg: {dark['code_bg']};
    --blockquote-bg: {dark['blockquote_bg']};
  }}
}}
html[data-theme="dark"] {{
  --page: {dark['page']};
  --surface: {dark['surface']};
  --text: {dark['text']};
  --muted: {dark['muted']};
  --header: {dark['header']};
  --border: {dark['border']};
  --accent: {dark['accent']};
  --accent-text: {dark['accent_text']};
  --zebra: {dark['zebra']};
  --total: {dark['total']};
  --chip-bg: {dark['chip_bg']};
  --warn-bg: {dark['warn_bg']};
  --warn-text: {dark['warn_text']};
  --warn-strong: {dark['warn_strong']};
  --code-bg: {dark['code_bg']};
  --blockquote-bg: {dark['blockquote_bg']};
}}
html[data-theme="light"] {{
  --page: {light['page']};
  --surface: {light['surface']};
  --text: {light['text']};
  --muted: {light['muted']};
  --header: {light['header']};
  --border: {light['border']};
  --accent: {light['accent']};
  --accent-text: {light['accent_text']};
  --zebra: {light['zebra']};
  --total: {light['total']};
  --chip-bg: {light['chip_bg']};
  --warn-bg: {light['warn_bg']};
  --warn-text: {light['warn_text']};
  --warn-strong: {light['warn_strong']};
  --code-bg: {light['code_bg']};
  --blockquote-bg: {light['blockquote_bg']};
}}
body {{
  font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 13px;
  line-height: 1.45;
  color: var(--text);
  background: var(--page);
  margin: 0;
  padding: 20px 24px 40px 24px;
}}
a {{ color: var(--accent); }}
.report-header {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 22px;
}}
.report-header h1 {{
  margin: 0 0 8px 0;
  font-size: 22px;
  color: var(--text);
  border: 0;
  padding: 0;
}}
.meta {{ color: var(--muted); font-size: 13px; margin: 4px 0; }}
.goal {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
.chips {{ margin-top: 14px; }}
.chip {{
  display: inline-block;
  background: var(--chip-bg);
  color: var(--accent-text);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px;
  margin-right: 8px;
  margin-top: 4px;
  font-weight: 700;
  font-size: 12px;
}}
.theme-toggle {{ float: right; font-size: 12px; }}
.theme-toggle button {{
  background: var(--header);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 10px;
  margin-left: 4px;
  cursor: pointer;
  font-size: 12px;
}}
h2 {{
  font-size: 16px;
  color: var(--accent);
  margin: 28px 0 10px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}}
h3 {{
  font-size: 14px;
  color: var(--accent-text);
  margin: 18px 0 8px 0;
}}
section {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px 8px 16px;
  margin: 14px 0 18px 0;
}}
table {{
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0 12px 0;
  background: var(--surface);
}}
th, td {{
  border: 1px solid var(--border);
  padding: 6px 8px;
  vertical-align: top;
}}
th {{
  background: var(--header);
  color: var(--accent-text);
  text-align: left;
  font-weight: 700;
}}
td.num, th.num {{ text-align: right; }}
tr:nth-child(even) td {{ background: var(--zebra); }}
tr.total td {{
  background: var(--total);
  font-weight: 700;
}}
tr.warn td {{ background: var(--warn-bg); }}
tr.warn td.rem {{ color: var(--warn-strong); font-weight: 700; }}
code {{
  background: var(--code-bg);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}}
blockquote, .note {{
  border-left: 3px solid var(--accent);
  margin: 8px 0 12px 0;
  padding: 6px 12px;
  background: var(--blockquote-bg);
  color: var(--muted);
}}
.empty {{ color: var(--muted); font-style: italic; margin: 8px 0; }}
.muted {{ color: var(--muted); font-size: 12px; }}
.chart-wrap {{ text-align: center; margin: 12px 0; }}
.chart-wrap img {{ max-width: 100%; height: auto; border: 1px solid var(--border); border-radius: 8px; }}
hr {{ border: 0; border-top: 1px solid var(--border); margin: 20px 0; }}
</style>"""


THEME_TOGGLE_SCRIPT = """
<script>
function setReportTheme(theme) {
  if (theme === 'auto') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', theme);
  }
  try { localStorage.setItem('sprintReportTheme', theme); } catch (e) {}
}
(function () {
  try {
    var saved = localStorage.getItem('sprintReportTheme');
    if (saved === 'light' || saved === 'dark' || saved === 'auto') {
      setReportTheme(saved);
    }
  } catch (e) {}
})();
</script>
"""
