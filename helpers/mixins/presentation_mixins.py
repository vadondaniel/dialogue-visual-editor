from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import (
    clamp_message_font_size,
    message_default_font_size,
    message_font_scale_for_size,
    next_message_font_size_for_token,
    strip_control_tokens,
)

NAME_INDEX_UID_RE = re.compile(r":[A-Za-z]:(\d+)(?::([A-Za-z0-9_]+))?$")
NAME_TOKEN_RE = re.compile(r"\\[Nn]\[(\d+)\]")
VAR_TOKEN_RE = re.compile(r"\\[Vv]\[(\d+)\]")
ICON_TOKEN_RE = re.compile(r"\\[Ii]\[(\d+)\]")
PARTY_TOKEN_RE = re.compile(r"\\[Pp]\[(\d+)\]")
CURRENCY_TOKEN_RE = re.compile(r"\\[Gg](?![A-Za-z0-9_])")
COLOR_TOKEN_RE = re.compile(r"\\[Cc]\[(\d+)\]")
HIDDEN_STYLE_TOKEN_RE = re.compile(
    r"""
    \\[Cc]\[(\d+)\]             |
    \\([{}])                    |
    \\[Ff][Ss]\[(\d+)\]         |
    \\[A-Za-z]+\d*<[^>]*>       |
    \\[A-Za-z]+\d*\[[^\]]*\]    |
    \\[\.\!\|\^]                |
    \\[ntr]
    """,
    re.VERBOSE,
)
PREVIEW_BASE_POINT_SIZE = 10.0

MaskedStyleSpan = tuple[int, int, str, float]


def is_dark_palette() -> bool:
    core_app = QApplication.instance()
    if core_app is None:
        return False
    app = cast(QApplication, core_app)
    try:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return False


class _EditorHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class PresentationHelpersMixin(_EditorHostTypingFallback):
    data_dir: Optional[Path]
    current_path: Optional[Path]
    sessions: dict[Path, FileSession]
    speaker_translation_map: dict[str, str]
    _windowskin_text_colors: dict[int, str]
    _windowskin_text_colors_loaded: bool
    if TYPE_CHECKING:
        def _normalize_translation_lines(self, value: Any) -> list[str]: ...
        def _normalize_speaker_key(self, value: str) -> str: ...
        def _speaker_translation_for_key(self, speaker_key: str) -> str: ...

    def _clamp_preview_font_size(self, value: int) -> int:
        return clamp_message_font_size(value)

    def _next_preview_font_size(self, token: str, current_font_size: int) -> int:
        return next_message_font_size_for_token(token, current_font_size)

    def _preview_font_scale(self, font_size: int) -> float:
        return message_font_scale_for_size(font_size)

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        lines = segment.source_lines or segment.original_lines or segment.lines
        return lines if lines else [""]

    def _selected_variable_label_version(self) -> str:
        resolver = getattr(self, "_selected_apply_version", None)
        if callable(resolver):
            try:
                selected = resolver()
                if selected in {"original", "working", "translated"}:
                    return cast(str, selected)
            except Exception:
                pass
        return "translated" if self._is_translator_mode() else "working"

    def _system_session(self) -> Optional[FileSession]:
        for path, session in self.sessions.items():
            if path.name.lower() == "system.json":
                return session
        return None

    def _system_variables_from_original_snapshot(self) -> dict[int, str]:
        session = self._system_session()
        if session is None:
            return {}
        if self.version_db is None:
            return {}
        try:
            payload = self.version_db.get_snapshot_payload(
                self._relative_path(session.path),
                "original",
            )
        except Exception:
            return {}
        if not payload:
            return {}
        try:
            decoded = json.loads(payload)
        except Exception:
            return {}
        if not isinstance(decoded, dict):
            return {}
        raw_variables = decoded.get("variables")
        if not isinstance(raw_variables, list):
            return {}
        mapped: dict[int, str] = {}
        for idx, value in enumerate(raw_variables):
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    mapped[idx] = cleaned
        return mapped

    def _system_variables_from_session(
        self,
        translated: bool,
        *,
        translated_fallback_to_source: bool = True,
    ) -> dict[int, str]:
        session = self._system_session()
        if session is None:
            return {}
        mapped: dict[int, str] = {}
        for segment in session.segments:
            path_tokens_raw = getattr(segment, "system_text_path", ())
            if not isinstance(path_tokens_raw, tuple):
                continue
            if len(path_tokens_raw) != 2:
                continue
            if path_tokens_raw[0] != "variables":
                continue
            variable_id = path_tokens_raw[1]
            if not isinstance(variable_id, int):
                continue
            if translated:
                translated_lines = self._normalize_translation_lines(
                    segment.translation_lines
                )
                text_value = "\n".join(translated_lines).strip()
                if not text_value and translated_fallback_to_source:
                    base_lines = (
                        segment.source_lines
                        or segment.original_lines
                        or segment.lines
                        or [""]
                    )
                    text_value = "\n".join(base_lines).strip()
            else:
                text_value = "\n".join(segment.lines or [""]).strip()
            if text_value:
                mapped[variable_id] = text_value
        return mapped

    def _variable_label_for_rpgm_index(self, variable_id: int) -> str:
        safe_id = max(0, int(variable_id))

        if self._is_translator_mode():
            translated_values = self._system_variables_from_session(
                translated=True,
                translated_fallback_to_source=False,
            )
            translated_label = translated_values.get(safe_id, "")
            if translated_label:
                return f"system.variables[{safe_id}]: {translated_label}"

        version = self._selected_variable_label_version()
        if version == "original":
            values = self._system_variables_from_original_snapshot()
            label = values.get(safe_id, "")
        elif version == "translated":
            values = self._system_variables_from_session(translated=True)
            label = values.get(safe_id, "")
        else:
            values = self._system_variables_from_session(translated=False)
            label = values.get(safe_id, "")

        if label:
            return f"system.variables[{safe_id}]: {label}"
        return f"system.variables[{safe_id}]: (empty)"

    def _name_index_kind(self, session: FileSession) -> str:
        raw_kind = getattr(session, "name_index_kind", "")
        if isinstance(raw_kind, str):
            cleaned = raw_kind.strip().lower()
            if cleaned:
                return cleaned
        if bool(getattr(session, "is_actor_index_session", False)):
            return "actor"
        if bool(getattr(session, "is_name_index_session", False)):
            return "entry"
        return ""

    def _is_name_index_session(self, session: FileSession) -> bool:
        return bool(self._name_index_kind(session))

    def _is_actor_index_session(self, session: FileSession) -> bool:
        return self._name_index_kind(session) == "actor"

    def _name_index_label(self, session: Optional[FileSession]) -> str:
        if session is None:
            return "Entry"
        raw = getattr(session, "name_index_label", "")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        kind = self._name_index_kind(session)
        if kind == "actor":
            return "Actor"
        if kind == "class":
            return "Class"
        if kind == "item":
            return "Item"
        if kind == "armor":
            return "Armor"
        if kind == "weapon":
            return "Weapon"
        if kind == "mapinfo":
            return "Map"
        if kind == "skill":
            return "Skill"
        if kind == "state":
            return "State"
        if kind == "tileset":
            return "Tileset"
        if kind == "troop":
            return "Troop"
        if kind == "enemy":
            return "Enemy"
        if kind == "system":
            return "System"
        if kind == "plugin":
            return "Plugin"
        return "Entry"

    def _name_index_uid_prefix(self, session: FileSession) -> str:
        raw = getattr(session, "name_index_uid_prefix", "")
        if isinstance(raw, str):
            cleaned = raw.strip()
            if cleaned:
                return cleaned
        kind = self._name_index_kind(session)
        if kind == "actor":
            return "A"
        if kind == "class":
            return "C"
        if kind == "item":
            return "I"
        if kind == "armor":
            return "R"
        if kind == "weapon":
            return "W"
        if kind == "mapinfo":
            return "M"
        if kind == "skill":
            return "K"
        if kind == "state":
            return "S"
        if kind == "tileset":
            return "T"
        if kind == "troop":
            return "P"
        if kind == "enemy":
            return "E"
        if kind == "system":
            return "Y"
        if kind == "plugin":
            return "J"
        return "A"

    def _actor_id_from_uid(self, uid: str) -> Optional[int]:
        match = NAME_INDEX_UID_RE.search(uid)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _name_index_field_from_uid(self, uid: str) -> str:
        match = NAME_INDEX_UID_RE.search(uid)
        if not match:
            return "name"
        raw_field = match.group(2)
        if isinstance(raw_field, str):
            cleaned = raw_field.strip()
            if cleaned:
                return cleaned
        return "name"

    def _matches_name_token(self, text: str) -> bool:
        return bool(NAME_TOKEN_RE.fullmatch(text or ""))

    def _actor_name_maps(self) -> tuple[dict[int, str], dict[int, str]]:
        jp_by_id: dict[int, str] = {}
        en_by_id: dict[int, str] = {}
        actor_session: Optional[FileSession] = None
        for session in self.sessions.values():
            if self._is_actor_index_session(session):
                actor_session = session
                break
        if actor_session is None:
            return jp_by_id, en_by_id

        for segment in actor_session.segments:
            actor_id = self._actor_id_from_uid(segment.uid)
            if actor_id is None:
                continue
            source_name = "\n".join(
                self._segment_source_lines_for_display(segment)).strip()
            if source_name:
                jp_by_id[actor_id] = source_name

            translated_name = "\n".join(
                self._normalize_translation_lines(segment.translation_lines)
            ).strip()
            if not translated_name and source_name:
                translated_name = self.speaker_translation_map.get(
                    self._normalize_speaker_key(source_name),
                    "",
                ).strip()
            if translated_name:
                en_by_id[actor_id] = translated_name
        return jp_by_id, en_by_id

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        if not text:
            return text
        jp_by_id, en_by_id = self._actor_name_maps()

        def replace_name(match: re.Match[str]) -> str:
            try:
                actor_id = int(match.group(1))
            except Exception:
                return match.group(0)
            if prefer_translated:
                translated = en_by_id.get(actor_id, "").strip()
                if translated:
                    return translated
            source_name = jp_by_id.get(actor_id, "").strip()
            if source_name:
                return source_name
            if unresolved_placeholder:
                return f"<N{actor_id}>"
            return match.group(0)

        return NAME_TOKEN_RE.sub(replace_name, text)

    def _resolve_speaker_display_name(self, raw_speaker: str) -> str:
        if not raw_speaker:
            return raw_speaker
        resolved = self._resolve_name_tokens_in_text(
            raw_speaker, prefer_translated=True).strip()
        if resolved and resolved != raw_speaker.strip():
            return resolved
        key = self._normalize_speaker_key(raw_speaker)
        translated = self._speaker_translation_for_key(key)
        return translated if translated else raw_speaker

    def _windowskin_path(self) -> Optional[Path]:
        if self.data_dir is None:
            return None
        candidate = self.data_dir.parent / "img" / "system" / "Window.png"
        if candidate.exists():
            return candidate
        fallback = self.data_dir / "img" / "system" / "Window.png"
        if fallback.exists():
            return fallback
        return None

    def _ensure_windowskin_text_colors(self) -> None:
        if self._windowskin_text_colors_loaded:
            return
        self._windowskin_text_colors_loaded = True
        self._windowskin_text_colors.clear()

        path = self._windowskin_path()
        if path is None:
            return

        try:
            image = QImage(str(path))
            if image.isNull():
                return
            for color_code in range(32):
                px = 96 + (color_code % 8) * 12 + 6
                py = 144 + (color_code // 8) * 12 + 6
                if px < 0 or py < 0 or px >= image.width() or py >= image.height():
                    continue
                pixel = image.pixelColor(px, py)
                self._windowskin_text_colors[color_code] = pixel.name(
                    QColor.NameFormat.HexRgb
                )
        except Exception:
            self._windowskin_text_colors.clear()

    def _color_for_rpgm_code(self, color_code: int) -> str:
        safe_code = max(0, int(color_code))
        if safe_code == 0:
            return ""
        self._ensure_windowskin_text_colors()
        normalized = safe_code % 32
        if normalized in self._windowskin_text_colors:
            return self._windowskin_text_colors[normalized]
        if safe_code in self._windowskin_text_colors:
            return self._windowskin_text_colors[safe_code]

        hue = (safe_code * 37) % 360
        lightness = 176 if is_dark_palette() else 96
        fallback = QColor.fromHsl(hue, 180, lightness)
        return fallback.name(QColor.NameFormat.HexRgb)

    def _blend_hex_colors(self, first_hex: str, second_hex: str, first_weight: float) -> str:
        first = QColor(first_hex)
        second = QColor(second_hex)
        if not first.isValid():
            return second.name(QColor.NameFormat.HexRgb) if second.isValid() else "#94a3b8"
        if not second.isValid():
            return first.name(QColor.NameFormat.HexRgb)

        w = max(0.0, min(1.0, float(first_weight)))
        r = int(round(first.red() * w + second.red() * (1.0 - w)))
        g = int(round(first.green() * w + second.green() * (1.0 - w)))
        b = int(round(first.blue() * w + second.blue() * (1.0 - w)))
        return QColor(r, g, b).name(QColor.NameFormat.HexRgb)

    def _muted_base_text_color(self) -> str:
        core_app = QApplication.instance()
        if core_app is None:
            return "#94a3b8"
        app = cast(QApplication, core_app)
        try:
            palette = app.palette()
            text_color = palette.color(QPalette.ColorRole.Text)
            base_color = palette.color(QPalette.ColorRole.Base)
            placeholder = palette.color(QPalette.ColorRole.PlaceholderText)

            if text_color.isValid() and base_color.isValid():
                # Keep hint text visibly dim by blending toward the editor base.
                muted_from_text = self._blend_hex_colors(
                    text_color.name(QColor.NameFormat.HexRgb),
                    base_color.name(QColor.NameFormat.HexRgb),
                    0.42,
                )
                if placeholder.isValid():
                    muted_from_placeholder = self._blend_hex_colors(
                        placeholder.name(QColor.NameFormat.HexRgb),
                        base_color.name(QColor.NameFormat.HexRgb),
                        0.72,
                    )
                    muted = QColor(muted_from_placeholder)
                    text = QColor(text_color)
                    # If placeholder-derived muted is still too close to normal text, force darker fallback.
                    distance = (
                        abs(muted.red() - text.red())
                        + abs(muted.green() - text.green())
                        + abs(muted.blue() - text.blue())
                    )
                    if distance < 54:
                        return muted_from_text
                    return muted_from_placeholder
                return muted_from_text

            if placeholder.isValid():
                return placeholder.name(QColor.NameFormat.HexRgb)
        except Exception:
            pass
        return "#94a3b8"

    def _muted_color_for_rpgm_code(self, color_code: int) -> str:
        base = self._color_for_rpgm_code(color_code)
        if not base:
            return ""
        return self._blend_hex_colors(base, self._muted_base_text_color(), 0.55)

    def _render_text_with_color_codes_html(
        self,
        text: str,
        muted: bool = False,
        show_style_tokens: bool = False,
    ) -> str:
        if not text:
            return ""

        resolved = self._resolve_name_tokens_in_text(
            text,
            prefer_translated=True,
            unresolved_placeholder=True,
        )
        resolved = VAR_TOKEN_RE.sub(lambda m: f"<V{m.group(1)}>", resolved)
        resolved = ICON_TOKEN_RE.sub(lambda m: f"<I{m.group(1)}>", resolved)
        resolved = PARTY_TOKEN_RE.sub(lambda m: f"<P{m.group(1)}>", resolved)
        resolved = CURRENCY_TOKEN_RE.sub("<G>", resolved)

        parts: list[str] = []
        cursor = 0
        active_color = ""
        active_font_size = message_default_font_size()
        default_color = self._muted_base_text_color() if muted else ""
        at_line_start = True

        def escape_with_preserved_indent(chunk: str) -> tuple[str, bool]:
            if not chunk:
                return "", at_line_start
            local_line_start = at_line_start
            html_parts: list[str] = []
            line_parts = chunk.split("\n")
            for idx, line in enumerate(line_parts):
                if idx > 0:
                    html_parts.append("<br/>")
                    local_line_start = True
                if not line:
                    continue
                if local_line_start:
                    lead_idx = 0
                    indent_parts: list[str] = []
                    while lead_idx < len(line):
                        ch = line[lead_idx]
                        if ch == " ":
                            indent_parts.append("&nbsp;")
                            lead_idx += 1
                            continue
                        if ch == "\t":
                            indent_parts.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                            lead_idx += 1
                            continue
                        break
                    escaped = "".join(indent_parts) + html.escape(line[lead_idx:])
                else:
                    escaped = html.escape(line)
                html_parts.append(escaped)
                local_line_start = False
            return "".join(html_parts), local_line_start

        def append_chunk(chunk: str, color_hex: str, font_scale: float) -> None:
            nonlocal at_line_start
            if not chunk:
                return
            escaped, at_line_start = escape_with_preserved_indent(chunk)
            effective_color = color_hex or default_color
            style_parts: list[str] = []
            if effective_color:
                style_parts.append(f"color: {effective_color};")
            if abs(font_scale - 1.0) > 0.01:
                point_size = max(1.0, PREVIEW_BASE_POINT_SIZE * font_scale)
                style_parts.append(f"font-size: {point_size:.1f}pt;")
            if style_parts:
                style_attr = " ".join(style_parts)
                parts.append(f"<span style=\"{style_attr}\">{escaped}</span>")
                return
            parts.append(escaped)

        for match in HIDDEN_STYLE_TOKEN_RE.finditer(resolved):
            append_chunk(
                resolved[cursor:match.start()],
                active_color,
                self._preview_font_scale(active_font_size),
            )
            token = match.group(0)
            color_group = match.group(1)
            if color_group is not None:
                try:
                    color_code = int(color_group)
                except Exception:
                    color_code = 0
                next_color = (
                    self._muted_color_for_rpgm_code(color_code)
                    if muted
                    else self._color_for_rpgm_code(color_code)
                )
                if show_style_tokens:
                    append_chunk(
                        token,
                        next_color,
                        self._preview_font_scale(active_font_size),
                    )
                active_color = next_color
                cursor = match.end()
                continue
            if show_style_tokens:
                append_chunk(
                    token,
                    active_color,
                    self._preview_font_scale(active_font_size),
                )
            active_font_size = self._next_preview_font_size(
                token, active_font_size)
            cursor = match.end()

        append_chunk(
            resolved[cursor:],
            active_color,
            self._preview_font_scale(active_font_size),
        )
        if parts:
            return "".join(parts)
        raw_source = resolved if show_style_tokens else strip_control_tokens(resolved)
        raw = html.escape(raw_source)
        if default_color and raw:
            return f"<span style=\"color: {default_color};\">{raw}</span>"
        return raw

    def _render_text_with_color_codes_html_muted(self, text: str) -> str:
        return self._render_text_with_color_codes_html(text, muted=True)

    def _render_text_with_visible_color_codes_html(self, text: str) -> str:
        return self._render_text_with_color_codes_html(
            text,
            muted=False,
            show_style_tokens=True,
        )

    def _hidden_control_line_with_color_spans(
        self,
        line: str,
    ) -> tuple[str, list[MaskedStyleSpan]]:
        resolved = self._resolve_name_tokens_in_text(
            line,
            prefer_translated=True,
            unresolved_placeholder=True,
        )
        resolved = VAR_TOKEN_RE.sub(lambda m: f"<V{m.group(1)}>", resolved)
        resolved = ICON_TOKEN_RE.sub(lambda m: f"<I{m.group(1)}>", resolved)
        resolved = PARTY_TOKEN_RE.sub(lambda m: f"<P{m.group(1)}>", resolved)
        resolved = CURRENCY_TOKEN_RE.sub("<G>", resolved)

        output_parts: list[str] = []
        spans: list[MaskedStyleSpan] = []
        cursor = 0
        out_pos = 0
        active_color = ""
        active_font_size = message_default_font_size()

        for match in HIDDEN_STYLE_TOKEN_RE.finditer(resolved):
            chunk = resolved[cursor:match.start()]
            if chunk:
                output_parts.append(chunk)
                next_pos = out_pos + len(chunk)
                spans.append(
                    (
                        out_pos,
                        next_pos,
                        active_color,
                        self._preview_font_scale(active_font_size),
                    )
                )
                out_pos = next_pos

            color_group = match.group(1)
            if color_group is not None:
                try:
                    color_code = int(color_group)
                except Exception:
                    color_code = 0
                active_color = self._color_for_rpgm_code(color_code)
            else:
                token = match.group(0)
                active_font_size = self._next_preview_font_size(
                    token, active_font_size)
            cursor = match.end()

        tail = resolved[cursor:]
        if tail:
            output_parts.append(tail)
            next_pos = out_pos + len(tail)
            spans.append(
                (
                    out_pos,
                    next_pos,
                    active_color,
                    self._preview_font_scale(active_font_size),
                )
            )
            out_pos = next_pos

        return "".join(output_parts), spans

    def _hidden_control_line_transform(self, line: str) -> str:
        masked, _spans = self._hidden_control_line_with_color_spans(line)
        return masked
