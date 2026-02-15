from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.audit.audit_search_mixin import AuditSearchMixin


class _Harness(AuditSearchMixin):
    pass


class AuditSearchMixinTests(unittest.TestCase):
    def test_audit_search_needle_preserves_whitespace_literal_query(self) -> None:
        harness = _Harness()
        query = " úr "

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=True,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query)

    def test_audit_search_needle_casefolds_literal_whitespace_query(self) -> None:
        harness = _Harness()
        query = " ÚR "

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=False,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query.casefold())

    def test_audit_search_needle_uses_literal_mode_for_control_queries(self) -> None:
        harness = _Harness()
        query = r"\N[3] úr"

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=True,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query)

    def test_audit_search_needle_uses_natural_mode_without_whitespace(self) -> None:
        harness = _Harness()
        query = "魔王"

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=False,
        )

        self.assertTrue(natural_mode)
        self.assertEqual(needle, query.casefold())


if __name__ == "__main__":
    unittest.main()
