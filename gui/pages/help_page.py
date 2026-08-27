"""In-app Help tab that renders the bundled GUI README.

QTextBrowser has a limited rich-text engine: ``width="100%"``, ``max-width``,
and SVG sizing are unreliable and often cause text to paint over images.
This page rasterizes README images to fixed-width PNGs before display.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import tempfile
from html import escape
from pathlib import Path

try:
    import markdown as _markdown
    _HAS_MD = True
    _MD_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    _HAS_MD = False
    _MD_IMPORT_ERR = repr(_e)

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from gui.settings import bundled_resource_root
from gui.theme import app_theme
from report_style import DARK, LIGHT

log = logging.getLogger(__name__)

_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r"""\bsrc=["']([^"']+)["']""", re.IGNORECASE)
_ALT_RE = re.compile(r"""\balt=["']([^"']*)["']""", re.IGNORECASE)


def _readme_path() -> Path:
    return bundled_resource_root() / "README.md"


def _help_css(theme: str) -> str:
    """Resolved Help stylesheet for QTextBrowser (light or dark)."""
    c = DARK if theme == "dark" else LIGHT
    return f"""
<style>
  body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13px;
    color: {c['text']};
    background: {c['page']};
    margin: 12px 18px 24px 18px;
  }}
  h1 {{
    font-size: 22px;
    color: {c['text']};
    border-bottom: 2px solid {c['accent']};
    padding-bottom: 6px;
    margin-top: 8px;
  }}
  h2 {{
    font-size: 17px;
    color: {c['accent']};
    margin-top: 28px;
    border-bottom: 1px solid {c['border']};
    padding-bottom: 4px;
  }}
  h3 {{
    font-size: 14px;
    color: {c['accent_text']};
    margin-top: 18px;
  }}
  table {{
    border-collapse: collapse;
    margin: 8px 0 16px 0;
    background: {c['surface']};
  }}
  th, td {{
    border: 1px solid {c['border']};
    padding: 4px 8px;
    vertical-align: top;
    color: {c['text']};
  }}
  th {{
    background: {c['header']};
    color: {c['accent_text']};
    text-align: left;
    font-weight: 600;
  }}
  td code, code {{
    background: {c['code_bg']};
    color: {c['text']};
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
  }}
  pre {{
    background: {c['blockquote_bg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 10px 12px;
    color: {c['text']};
  }}
  tr:nth-child(even) td {{ background: {c['zebra']}; }}
  blockquote {{
    border-left: 3px solid {c['accent']};
    margin: 8px 0;
    padding: 4px 12px;
    background: {c['blockquote_bg']};
    color: {c['muted']};
  }}
  hr {{
    border: 0;
    border-top: 1px solid {c['border']};
    margin: 18px 0;
  }}
  p, li {{
    line-height: 1.45;
    margin: 8px 0;
    color: {c['text']};
  }}
  ul, ol {{ margin: 8px 0 8px 22px; color: {c['text']}; }}
  strong {{ color: {c['text']}; }}
  a {{ color: {c['accent']}; }}
  em {{ color: {c['muted']}; }}
</style>
"""


def _resolve_image_path(src: str, root: Path) -> Path | None:
    raw = src.strip()
    if raw.startswith("file:"):
        local = QUrl(raw).toLocalFile()
        path = Path(local) if local else None
    else:
        path = Path(raw)
        if not path.is_absolute():
            path = (root / raw.lstrip("./")).resolve()
    if path is None or not path.is_file():
        return None
    return path


def _rasterize_to_png(src_path: Path, dest_png: Path, target_width: int) -> tuple[int, int] | None:
    """Render an image file to a PNG no wider than ``target_width``. Return (w, h)."""
    target_width = max(240, int(target_width))
    suffix = src_path.suffix.lower()

    if suffix == ".svg":
        try:
            from PySide6.QtSvg import QSvgRenderer
        except Exception:
            log.warning("QtSvg unavailable; cannot rasterize %s", src_path)
            return None
        renderer = QSvgRenderer(str(src_path))
        if not renderer.isValid():
            log.warning("Invalid SVG: %s", src_path)
            return None
        default = renderer.defaultSize()
        if default.width() <= 0 or default.height() <= 0:
            vb = renderer.viewBox()
            if vb.width() > 0 and vb.height() > 0:
                default = QSize(int(vb.width()), int(vb.height()))
            else:
                default = QSize(1200, 380)
        width = min(target_width, max(default.width(), 1))
        height = max(1, int(round(width * default.height() / default.width())))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
    else:
        image = QImage(str(src_path))
        if image.isNull():
            log.warning("Could not load image: %s", src_path)
            return None
        if image.width() > target_width:
            image = image.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
        width, height = image.width(), image.height()

    dest_png.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(dest_png), "PNG"):
        log.warning("Failed to save rasterized image: %s", dest_png)
        return None
    return width, height


def _cache_key(path: Path, target_width: int) -> str:
    st = path.stat()
    blob = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{target_width}".encode()
    return hashlib.sha1(blob).hexdigest()[:16]


def _rewrite_images(html: str, root: Path, cache_dir: Path, target_width: int) -> str:
    """Replace README images with fixed-size PNGs that QTextBrowser can lay out."""

    cache_root = cache_dir.resolve()

    def replace_img(img_tag: str) -> str:
        src_m = _SRC_RE.search(img_tag)
        if not src_m:
            return img_tag

        if re.search(r'\bwidth="\d+"', img_tag) and re.search(r'\bheight="\d+"', img_tag):
            src_path = _resolve_image_path(src_m.group(1), root)
            if src_path is not None:
                try:
                    if cache_root in src_path.resolve().parents or src_path.resolve().parent == cache_root:
                        return img_tag
                except OSError:
                    pass

        src_path = _resolve_image_path(src_m.group(1), root)
        if src_path is None:
            return (
                "<p style='color:#a00;'><em>Image missing: "
                f"{escape(src_m.group(1))}</em></p>"
            )

        key = _cache_key(src_path, target_width)
        dest = cache_dir / f"{key}_{src_path.stem}.png"
        size = None
        if dest.is_file():
            pix = QPixmap(str(dest))
            if not pix.isNull():
                size = (pix.width(), pix.height())
        if size is None:
            size = _rasterize_to_png(src_path, dest, target_width)
        if size is None:
            return (
                "<p style='color:#a00;'><em>Could not render image: "
                f"{escape(src_path.name)}</em></p>"
            )

        width, height = size
        alt_m = _ALT_RE.search(img_tag)
        alt = escape(alt_m.group(1)) if alt_m else escape(src_path.name)
        url = QUrl.fromLocalFile(str(dest.resolve())).toString()
        return (
            f'<p align="center">'
            f'<img src="{url}" width="{width}" height="{height}" alt="{alt}" />'
            f"</p>"
        )

    html = _IMG_TAG_RE.sub(lambda m: replace_img(m.group(0)), html)
    html = re.sub(
        r"<p\b[^>]*>\s*(<p align=\"center\">.*?</p>)\s*</p>",
        r"\1",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html


def _markdown_to_body(text: str) -> str:
    if _HAS_MD:
        try:
            return _markdown.markdown(
                text,
                extensions=["tables", "fenced_code", "md_in_html"],
            )
        except Exception as exc:
            log.exception("README markdown render failed")
            return (
                f"<p style='color:#a00;'>Could not render Help markdown: "
                f"{escape(str(exc))}</p><pre>{escape(text)}</pre>"
            )
    return (
        "<p style='color:#a00;'>Note: the <code>markdown</code> package is "
        f"unavailable ({escape(_MD_IMPORT_ERR)}). Showing raw text.</p>"
        f"<pre>{escape(text)}</pre>"
    )


def _render_readme_html(
    text: str, root: Path, cache_dir: Path, target_width: int, theme: str,
) -> str:
    body = _markdown_to_body(text)
    body = _rewrite_images(body, root, cache_dir, target_width)
    return f"<html><head>{_help_css(theme)}</head><body>{body}</body></html>"


class HelpPage(QWidget):
    """Shows the GUI README bundled with the app."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        try:
            import PySide6.QtSvg  # noqa: F401
        except Exception:
            log.debug("PySide6.QtSvg not available; SVG Help images may fail", exc_info=True)

        self.title = QLabel("Help")
        self.subtitle = QLabel(
            "How to use the app (capsules + Generate review). Export file layout is at the end."
        )
        self.subtitle.setWordWrap(True)
        self._apply_chrome_styles()

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)

        self._cache_dir = Path(tempfile.mkdtemp(prefix="sprintreport-help-"))
        self._readme_text: str | None = None
        self._last_width = 0
        self._last_theme = ""
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(150)
        self._reload_timer.timeout.connect(self._reload_for_current_width)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.view, stretch=1)

        self.reload()

    def _apply_chrome_styles(self) -> None:
        theme = app_theme()
        c = DARK if theme == "dark" else LIGHT
        self.title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {c['text']}; margin: 0;"
        )
        self.subtitle.setStyleSheet(f"color: {c['muted']};")
        self.setStyleSheet(f"HelpPage {{ background: {c['page']}; }}")

    def cleanup(self) -> None:
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.cleanup()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reload_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_chrome_styles()
        # Force re-theme when returning to Help (palette may have changed).
        self._last_theme = ""
        self._reload_timer.start()

    def _content_width(self) -> int:
        w = self.view.viewport().width() - 48
        if w < 320:
            w = max(320, self.width() - 80)
        return min(w, 1100)

    def reload(self) -> None:
        path = _readme_path()
        theme = app_theme()
        css = _help_css(theme)
        if not path.is_file():
            self._readme_text = None
            self.view.setHtml(
                f"<html><head>{css}</head><body>"
                f"<h2>Help unavailable</h2>"
                f"<p>Could not find <code>{escape(str(path))}</code>.</p>"
                f"<p>When building the executable, ensure <code>README.md</code> "
                f"and <code>assets/readme/</code> are included in the PyInstaller datas.</p>"
                f"</body></html>"
            )
            return
        try:
            self._readme_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._readme_text = None
            self.view.setHtml(
                f"<html><head>{css}</head><body>"
                f"<h2>Help unavailable</h2>"
                f"<p>Failed to read README: {escape(str(exc))}</p>"
                f"</body></html>"
            )
            return
        self._last_width = 0
        self._last_theme = ""
        self._reload_for_current_width()

    def _reload_for_current_width(self) -> None:
        if self._readme_text is None:
            return
        width = self._content_width()
        theme = app_theme()
        if (
            self._last_width
            and abs(width - self._last_width) < 24
            and theme == self._last_theme
        ):
            return
        self._apply_chrome_styles()
        root = bundled_resource_root()
        self.view.document().setBaseUrl(QUrl.fromLocalFile(str(root) + "/"))
        html = _render_readme_html(
            self._readme_text, root, self._cache_dir, width, theme,
        )
        scroll_y = self.view.verticalScrollBar().value()
        self.view.setHtml(html)
        self.view.verticalScrollBar().setValue(scroll_y)
        self._last_width = width
        self._last_theme = theme
