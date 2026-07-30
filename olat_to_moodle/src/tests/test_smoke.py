"""Prüft nur, dass pytest die Kernmodule importieren kann (pythonpath korrekt)."""


def test_can_import_core_modules():
    import config  # noqa: F401
    from conversion import html_cleaner  # noqa: F401
    from conversion import olat_parser  # noqa: F401
