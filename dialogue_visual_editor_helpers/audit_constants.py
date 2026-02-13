from __future__ import annotations

import re

SANITIZE_CHAR_RULES: list[tuple[str, str, str, str]] = [
    ("jp_open_double_ascii", 'JP: 「 -> "', "「", '"'),
    ("jp_close_double_ascii", 'JP: 」 -> "', "」", '"'),
    ("jp_open_single_ascii", "JP: 『 -> '", "『", "'"),
    ("jp_close_single_ascii", "JP: 』 -> '", "』", "'"),
    ("jp_comma_ascii", "JP: 、 -> ,", "、", ","),
    ("jp_period_ascii", "JP: 。 -> .", "。", "."),
    ("jp_exclamation_ascii", "JP: ！ -> !", "！", "!"),
    ("jp_question_ascii", "JP: ？ -> ?", "？", "?"),
    ("jp_colon_ascii", "JP: ： -> :", "：", ":"),
    ("jp_semicolon_ascii", "JP: ； -> ;", "；", ";"),
    ("jp_open_paren_ascii", "JP: （ -> (", "（", "("),
    ("jp_close_paren_ascii", "JP: ） -> )", "）", ")"),
    ("jp_open_bracket_ascii", "JP: ［ -> [", "［", "["),
    ("jp_close_bracket_ascii", "JP: ］ -> ]", "］", "]"),
    ("jp_open_brace_ascii", "JP: ｛ -> {", "｛", "{"),
    ("jp_close_brace_ascii", "JP: ｝ -> }", "｝", "}"),
    ("jp_wave_ascii", "JP: 〜 -> ~", "〜", "~"),
    ("jp_fullwidth_wave_ascii", "JP: ～ -> ~", "～", "~"),
    ("ellipsis_ascii", "Ellipsis: … -> ...", "…", "..."),
    ("jp_ideographic_space_ascii", "JP: IDEOGRAPHIC SPACE -> SPACE", "　", " "),
    ("en_left_double_ascii", 'EN: “ -> "', "“", '"'),
    ("en_right_double_ascii", 'EN: ” -> "', "”", '"'),
    ("en_left_single_ascii", "EN: ‘ -> '", "‘", "'"),
    ("en_right_single_ascii", "EN: ’ -> '", "’", "'"),
    ("en_em_dash_ascii", "EN: — -> -", "—", "-"),
    ("en_en_dash_ascii", "EN: – -> -", "–", "-"),
    ("en_nbsp_ascii", "EN: NBSP -> SPACE", "\u00A0", " "),
]

COLOR_CODE_TOKEN_RE = re.compile(r"\\[Cc]\[(\d+)\]$")
