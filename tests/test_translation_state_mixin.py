from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY
from dialogue_visual_editor.helpers.mixins.translation_state_mixin import (
    TranslationStateMixin,
)


def _segment(uid: str, text: str, speaker: str = "") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
    )


class _Harness(TranslationStateMixin):
    def __init__(self) -> None:
        self.translation_state: dict[str, Any] = {
            "version": 1,
            "uid_counter": 0,
            "speaker_map": {},
            "files": {},
        }
        self.active_translation_profile_id = "default"
        self.translation_profiles_meta: dict[str, dict[str, Any]] = {
            "default": {
                "name": "Default",
                "target_language_code": "en",
                "prompt_template": self._default_translation_prompt_template(),
            }
        }
        self.translation_state_path: Path | None = None
        self.speaker_translation_map: dict[str, str] = {}
        self.translation_uid_counter = 0
        self.sessions: dict[Path, FileSession] = {}

    def _relative_path(self, path: Path) -> str:
        return path.name

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        return segment.speaker_name

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return (
            text.replace("\\N[1]", "Alice")
            .replace("\\n[1]", "Alice")
            .replace("\\N[2]", "Bob")
            .replace("\\n[2]", "Bob")
        )


class TranslationStateMixinTests(unittest.TestCase):
    def test_build_human_translation_reference_prompt_resolves_name_tokens(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "\\N[1] says hi", "\\N[2]")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            0,
        )

        self.assertIn('{Bob}: "Alice says hi"', prompt)
        self.assertNotIn("\\N[1]", prompt)
        self.assertNotIn("\\N[2]", prompt)

    def test_build_human_translation_reference_prompt_includes_neighbors(self) -> None:
        harness = _Harness()
        before_segment = _segment("Map001.json:L0:0", "Before line", "Hero")
        before_segment.translation_speaker = "Hero EN"
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        current.translation_speaker = "Mage EN"
        current.translation_lines = ["Existing TL"]
        after_segment = _segment("Map001.json:L0:2", "After line", "Villain")
        after_segment.translation_speaker = "Villain EN"
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[before_segment, current, after_segment],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            1,
        )

        self.assertIn(
            "Translate the following dialogue from JA to EN.",
            prompt,
        )
        self.assertIn(
            "Write natural, fluent game dialogue.",
            prompt,
        )
        self.assertIn("Preserve intent, tone, and character voice.", prompt)
        self.assertIn("Transcript:", prompt)
        self.assertNotIn("context", prompt.lower())
        self.assertNotIn("selected line", prompt.lower())
        self.assertNotIn("chunk", prompt.lower())
        self.assertNotIn("same number of lines", prompt.lower())
        self.assertNotIn("same `{speaker}", prompt.lower())
        self.assertIn('Hero EN: "Before line"', prompt)
        self.assertIn('Mage EN: "Current line"', prompt)
        self.assertIn('Villain EN: "After line"', prompt)

    def test_build_human_translation_reference_prompt_zero_neighbors(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            0,
        )

        self.assertIn('{Mage}: "Current line"', prompt)
        self.assertNotIn("[CURRENT]", prompt)

    def test_build_human_translation_reference_prompt_returns_empty_for_missing_segment(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        missing = _segment("Map001.json:L0:999", "Missing", "Ghost")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            missing,
            2,
        )

        self.assertEqual(prompt, "")

    def test_other_profile_translations_include_other_profiles_for_same_segment(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Szia"]
        source_hash = harness._segment_source_hash(current)
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )
        harness.sessions = {session.path: session}
        harness.active_translation_profile_id = "hu"
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "hu",
            "profiles": {
                "hu": {
                    "name": "Hungarian",
                    "uid_counter": 1,
                    "target_language_code": "hu",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_hu"],
                            "entries": {
                                "T_hu": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Szia"],
                                }
                            },
                        }
                    },
                },
                "en": {
                    "name": "English",
                    "uid_counter": 1,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_en"],
                            "entries": {
                                "T_en": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Hello"],
                                }
                            },
                        }
                    },
                },
            },
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [("en", "English", "Hello")])

    def test_other_profile_translations_include_other_profiles_for_non_dialogue(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:M:1:displayName", "JP map name")
        current.segment_kind = "map_display_name"
        current.translation_lines = ["HU map name"]
        source_hash = harness._segment_source_hash(current)
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[current],
        )
        harness.sessions = {session.path: session}
        harness.active_translation_profile_id = "hu"
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "hu",
            "profiles": {
                "hu": {
                    "name": "Hungarian",
                    "uid_counter": 1,
                    "target_language_code": "hu",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {"Map001.json": {"order": [], "entries": {}}},
                },
                "en": {
                    "name": "English",
                    "uid_counter": 1,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_en_map"],
                            "entries": {
                                "T_en_map": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["EN map name"],
                                }
                            },
                        }
                    },
                },
            },
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [("en", "English", "EN map name")])

    def test_other_profile_translations_ignore_same_profile_matches(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Current TL"]
        same_source_other = _segment("Map001.json:L0:1", "JP line")
        same_source_other.translation_lines = ["Alt TL A"]

        session_current = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current, same_source_other],
        )
        harness.sessions = {
            session_current.path: session_current,
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session_current,
            current,
        )

        self.assertEqual(rows, [])

    def test_other_profile_translations_none_when_no_alternatives(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Same TL"]
        same_translation = _segment("Map001.json:L0:1", "JP line")
        same_translation.translation_lines = ["Same TL"]

        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current, same_translation],
        )
        harness.sessions = {session.path: session}

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [])

    def test_apply_state_script_message_legacy_hash_still_matches(self) -> None:
        harness = _Harness()
        segment = _segment("Map010.json:L0:0", "JP line", "Narrator")
        segment.segment_kind = "script_message"
        segment.code101["parameters"] = ["face", 0, 0, 2, "Narrator"]
        session = FileSession(
            path=Path("Map010.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )
        legacy_payload = "\n".join(
            [
                segment.segment_kind,
                segment.context,
                str(segment.background),
                str(segment.position),
                "",
                "0",
                segment.speaker_name,
                "\n".join(segment.lines),
            ]
        )
        legacy_hash = hashlib.sha1(legacy_payload.encode("utf-8")).hexdigest()
        harness.translation_state["files"] = {
            "Map010.json": {
                "order": ["T_legacy"],
                "entries": {
                    "T_legacy": {
                        "source_uid": segment.uid,
                        "source_hash": legacy_hash,
                        "translation_lines": ["TL line"],
                    }
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL line"])
        self.assertEqual(session.segments[0].tl_uid, "T_legacy")

    def test_apply_state_name_index_prefers_source_uid_mapping(self) -> None:
        harness = _Harness()
        seg_a = _segment("States.json:S:1:message1", "JP A")
        seg_b = _segment("States.json:S:1:message2", "JP B")
        session = FileSession(
            path=Path("States.json"),
            data=[],
            bundles=[],
            segments=[seg_a, seg_b],
        )
        setattr(session, "is_name_index_session", True)

        harness.translation_state["files"] = {
            "States.json": {
                "order": ["T_B", "T_A"],
                "entries": {
                    "T_A": {
                        "source_uid": "States.json:S:1:message1",
                        "source_hash": "old-a",
                        "translation_lines": ["TL A"],
                    },
                    "T_B": {
                        "source_uid": "States.json:S:1:message2",
                        "source_hash": "old-b",
                        "translation_lines": ["TL B"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL A"])
        self.assertEqual(session.segments[1].translation_lines, ["TL B"])
        self.assertEqual(session.segments[0].translation_speaker, "")
        self.assertEqual(session.segments[1].translation_speaker, "")
        self.assertEqual([seg.uid for seg in session.segments], [seg_a.uid, seg_b.uid])

    def test_apply_state_inserts_translation_only_segments_in_saved_order(self) -> None:
        harness = _Harness()
        seg_1 = _segment("Map001.json:L0:0", "JP 1", "Hero")
        seg_2 = _segment("Map001.json:L0:1", "JP 2", "Hero")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[seg_1, seg_2],
        )
        hash_1 = harness._segment_source_hash(seg_1)
        hash_2 = harness._segment_source_hash(seg_2)
        harness.translation_state["files"] = {
            "Map001.json": {
                "order": ["T1", "T_INSERT", "T2"],
                "entries": {
                    "T1": {
                        "source_uid": seg_1.uid,
                        "source_hash": hash_1,
                        "translation_lines": ["TL 1"],
                    },
                    "T_INSERT": {
                        "source_uid": "",
                        "source_hash": "",
                        "translation_only": True,
                        "translation_lines": ["TL insert"],
                        "source_lines": [""],
                        "original_lines": [""],
                    },
                    "T2": {
                        "source_uid": seg_2.uid,
                        "source_hash": hash_2,
                        "translation_lines": ["TL 2"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(len(session.segments), 3)
        self.assertFalse(session.segments[0].translation_only)
        self.assertTrue(session.segments[1].translation_only)
        self.assertFalse(session.segments[2].translation_only)
        self.assertEqual(session.segments[1].translation_lines, ["TL insert"])
        original_order = getattr(session, "_original_tl_order", [])
        self.assertEqual(len(original_order), 3)

    def test_translation_state_for_name_index_clears_speaker_fields(self) -> None:
        harness = _Harness()
        segment = _segment("System.json:Y:1:gameTitle", "JP title", r"\C[2]\N[1]\C[0]")
        segment.translation_lines = ["EN title"]
        segment.translation_speaker = "Should Not Persist"
        session = FileSession(
            path=Path("System.json"),
            data={},
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)

        state = harness._translation_state_for_session(session)
        self.assertEqual(len(state["order"]), 1)
        entry = state["entries"][state["order"][0]]
        self.assertEqual(entry["speaker_jp"], NO_SPEAKER_KEY)
        self.assertEqual(entry["speaker_en"], "")

    def test_load_translation_state_migrates_v1_to_v2(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            payload = {
                "version": 1,
                "uid_counter": 12,
                "speaker_map": {"Hero": "Aki"},
                "files": {
                    "Map001.json": {
                        "order": ["T00000012"],
                        "entries": {
                            "T00000012": {
                                "source_uid": "Map001.json:L0:0",
                                "source_hash": "abc",
                                "translation_lines": ["TL line"],
                            }
                        },
                    }
                },
            }
            state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            harness.translation_state_path = state_path
            harness._load_translation_state()

        self.assertEqual(harness.translation_state.get("version"), 2)
        self.assertEqual(harness.active_translation_profile_id, "default")
        self.assertEqual(harness.translation_state.get("source_language_code"), "ja")
        profiles = harness.translation_state.get("profiles")
        self.assertIsInstance(profiles, dict)
        default_profile = profiles.get("default") if isinstance(profiles, dict) else None
        self.assertIsInstance(default_profile, dict)
        if isinstance(default_profile, dict):
            self.assertEqual(default_profile.get("uid_counter"), 12)
            self.assertEqual(default_profile.get("speaker_map"), {"Hero": "Aki"})
            self.assertEqual(default_profile.get("target_language_code"), "en")
            prompt_template = default_profile.get("prompt_template")
            self.assertTrue(isinstance(prompt_template, str))
            if isinstance(prompt_template, str):
                self.assertIn("{payload_json}", prompt_template)
            files = default_profile.get("files")
            self.assertTrue(isinstance(files, dict) and "Map001.json" in files)

    def test_language_and_prompt_settings_normalization(self) -> None:
        harness = _Harness()
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "default",
            "source_language_code": "JA_JP",
            "profiles": {
                "default": {
                    "name": "Default",
                    "uid_counter": 0,
                    "target_language_code": "EN-US",
                    "prompt_template": "  Keep honorifics.  ",
                    "speaker_map": {},
                    "files": {},
                }
            },
        }
        source_lang = harness._translation_project_source_language_code()
        target_lang = harness._translation_profile_target_language_code("default")
        prompt_template = harness._translation_profile_prompt_template("default")
        self.assertEqual(source_lang, "ja-jp")
        self.assertEqual(target_lang, "en-us")
        self.assertEqual(prompt_template, "Keep honorifics.")

    def test_apply_state_uses_active_profile_and_keeps_speaker_map_isolated(self) -> None:
        harness = _Harness()
        seg = _segment("Map001.json:L0:0", "JP line", "Hero")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[seg],
        )
        source_hash = harness._segment_source_hash(seg)
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "alt",
            "profiles": {
                "default": {
                    "name": "Default",
                    "uid_counter": 1,
                    "speaker_map": {"Hero": "Default Hero"},
                    "files": {
                        "Map001.json": {
                            "order": ["T_default"],
                            "entries": {
                                "T_default": {
                                    "source_uid": seg.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Default TL"],
                                }
                            },
                        }
                    },
                },
                "alt": {
                    "name": "Alt",
                    "uid_counter": 2,
                    "speaker_map": {"Hero": "Alt Hero"},
                    "files": {
                        "Map001.json": {
                            "order": ["T_alt"],
                            "entries": {
                                "T_alt": {
                                    "source_uid": seg.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Alt TL"],
                                }
                            },
                        }
                    },
                },
            },
        }
        harness.active_translation_profile_id = "alt"
        profile_state = harness._active_profile_state()
        speaker_map_raw = profile_state.get("speaker_map")
        harness.speaker_translation_map = (
            dict(speaker_map_raw) if isinstance(speaker_map_raw, dict) else {}
        )
        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["Alt TL"])
        self.assertEqual(session.segments[0].translation_speaker, "Alt Hero")
        self.assertEqual(harness.speaker_translation_map.get("Hero"), "Alt Hero")

    def test_save_translation_state_updates_only_active_profile(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            harness.translation_state_path = state_path

            seg = _segment("Map001.json:L0:0", "JP", "Hero")
            seg.tl_uid = "T_alt"
            seg.translation_lines = ["Alt TL"]
            seg.translation_speaker = "Alt Hero"
            session = FileSession(
                path=Path("Map001.json"),
                data=[],
                bundles=[],
                segments=[seg],
            )
            harness.sessions = {session.path: session}
            harness.speaker_translation_map = {"Hero": "Alt Hero"}
            harness.translation_uid_counter = 7
            harness.active_translation_profile_id = "alt"
            harness.translation_state = {
                "version": 2,
                "active_profile_id": "alt",
                "profiles": {
                    "default": {
                        "name": "Default",
                        "uid_counter": 1,
                        "speaker_map": {"Hero": "Default Hero"},
                        "files": {"Map001.json": {"order": ["T_default"], "entries": {}}},
                    },
                    "alt": {
                        "name": "Alt",
                        "uid_counter": 3,
                        "speaker_map": {},
                        "files": {},
                    },
                },
            }

            saved = harness._save_translation_state([session.path])
            self.assertTrue(saved)

            profiles = harness.translation_state.get("profiles")
            self.assertIsInstance(profiles, dict)
            if isinstance(profiles, dict):
                default_profile = profiles.get("default")
                alt_profile = profiles.get("alt")
                self.assertIsInstance(default_profile, dict)
                self.assertIsInstance(alt_profile, dict)
                if isinstance(default_profile, dict):
                    self.assertEqual(default_profile.get("uid_counter"), 1)
                    self.assertEqual(default_profile.get("speaker_map"), {"Hero": "Default Hero"})
                if isinstance(alt_profile, dict):
                    self.assertEqual(alt_profile.get("uid_counter"), 7)
                    self.assertEqual(alt_profile.get("speaker_map"), {"Hero": "Alt Hero"})
                    files = alt_profile.get("files")
                    self.assertTrue(isinstance(files, dict) and "Map001.json" in files)

            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(written.get("version"), 2)
            self.assertEqual(written.get("active_profile_id"), "alt")


if __name__ == "__main__":
    unittest.main()
