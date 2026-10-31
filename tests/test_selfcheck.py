"""The packaged app's --self-check, run from the source tree.

The release build trusts it to stop a frozen app that lost a module or a data
file, so it has to pass on a complete tree and fail when a piece is missing.
"""


def test_a_complete_tree_passes(qapp, tmp_path):
    from wintranslate import selfcheck

    report = tmp_path / "report.txt"
    status = selfcheck.run(report)
    assert status == 0, report.read_text(encoding="utf-8")
    assert report.read_text(encoding="utf-8").endswith("0 failure(s)\n")


def test_missing_flags_fail_it(qapp, tmp_path, monkeypatch):
    from wintranslate import flags, selfcheck

    # What a spec that forgot the assets folder would ship.
    monkeypatch.setattr(flags, "FLAG_DIR", tmp_path / "no-assets" / "flags")
    report = tmp_path / "report.txt"
    assert selfcheck.run(report) == 1
    assert "FAIL flag svg" in report.read_text(encoding="utf-8")


def test_missing_theme_assets_fail_it(qapp, tmp_path, monkeypatch):
    from wintranslate import selfcheck, theme

    monkeypatch.setattr(theme, "ASSETS", tmp_path / "no-assets" / "ui")
    report = tmp_path / "report.txt"
    assert selfcheck.run(report) == 1
    assert "FAIL theme assets" in report.read_text(encoding="utf-8")
