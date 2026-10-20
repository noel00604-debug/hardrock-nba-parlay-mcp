"""Local dashboard file helpers: write a self-contained HTML report and open it in the default browser."""

from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from . import schemas as S

_CSS = (
    "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:24px;color:#1b1b1b;background:#fff}"
    "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}"
    "th{background:#f3f3f3}.muted{color:#666}pre{background:#f7f7f7;padding:8px;overflow:auto}"
)


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _render_value(value: Any) -> str:
    if isinstance(value, dict):
        rows = "".join(f"<tr><th>{_e(k)}</th><td>{_render_value(v)}</td></tr>" for k, v in value.items())
        return f"<table>{rows}</table>" if rows else '<span class="muted">(empty)</span>'
    if isinstance(value, list):
        if not value:
            return '<span class="muted">(none)</span>'
        if all(isinstance(item, dict) for item in value):
            keys: list[str] = []
            for item in value:
                for k in item:
                    if k not in keys:
                        keys.append(k)
            head = "".join(f"<th>{_e(k)}</th>" for k in keys)
            body = "".join(
                "<tr>" + "".join(f"<td>{_render_value(item.get(k))}</td>" for k in keys) + "</tr>"
                for item in value
            )
            return f"<table><tr>{head}</tr>{body}</table>"
        return "<ul>" + "".join(f"<li>{_render_value(item)}</li>" for item in value) + "</ul>"
    return _e(value)


def render_report_html(title: str, data: Any) -> str:
    """Generic, escaped HTML rendering of a report (a pydantic model or a plain dict). No scripts, no assets."""
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    parts = [
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{_e(title)}</h1>",
        f'<p class="muted">{_e(S.AI_DISCLOSURE)}</p>',
        _render_value(payload),
        "</body></html>",
    ]
    return "".join(parts)


def write_dashboard(report_html: str, out_path: str | Path) -> Path:
    """Write the HTML to ``out_path`` (parent directories created) and return the resolved path."""
    path = Path(out_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_html, encoding="utf-8")
    return path.resolve()


def open_in_browser(path: str | Path) -> bool:
    """Open a local file in the default browser. Never called from tests."""
    return webbrowser.open(Path(path).resolve().as_uri())
