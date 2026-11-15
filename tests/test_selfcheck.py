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


def test_a_build_with_only_the_mock_speech_engine_fails_it(qapp, tmp_path, monkeypatch):
    from wintranslate import selfcheck, speech

    # What a spec that dropped the real engine plugins would ship: Qt's mock
    # engine reads nothing aloud, so it must not count as a working one.
    monkeypatch.setattr(speech, "available_engines", lambda: ["mock"])
    report = tmp_path / "report.txt"
    assert selfcheck.run(report) == 1
    assert "FAIL text to speech" in report.read_text(encoding="utf-8")


def test_the_speech_check_ignores_the_tests_engine_override(qapp, tmp_path):
    """conftest forces the mock engine for the popup tests; the self-check
    must still look for the engine the app would choose on its own."""
    from wintranslate import selfcheck

    report = tmp_path / "report.txt"
    selfcheck.run(report)
    line = next(
        line for line in report.read_text(encoding="utf-8").splitlines()
        if "text to speech" in line
    )
    assert line.startswith("ok") and "mock" not in line, line


def test_a_frozen_build_carrying_ffmpeg_or_the_mock_engine_fails_it(
    qapp, tmp_path, monkeypatch
):
    import sys

    from wintranslate import selfcheck

    bundle = tmp_path / "bundle"
    (bundle / "PySide6" / "plugins" / "texttospeech").mkdir(parents=True)
    (bundle / "PySide6" / "plugins" / "texttospeech" / "qtexttospeech_mock.dll").touch()
    (bundle / "PySide6" / "avcodec-61.dll").touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    report = tmp_path / "report.txt"
    assert selfcheck.run(report) == 1
    text = report.read_text(encoding="utf-8")
    assert "FAIL lean bundle" in text
    assert "avcodec-61.dll" in text and "qtexttospeech_mock.dll" in text


def test_a_bundled_engine_that_finds_no_voice_here_is_reported_not_failed(
    qapp, tmp_path, monkeypatch
):
    """A CI runner may have no voice or audio device. That is the machine,
    not the package, so it must not stop a release."""
    from wintranslate import selfcheck, speech

    monkeypatch.setattr(speech, "available_engines", lambda: ["winrt", "sapi", "mock"])
    monkeypatch.setattr(
        speech,
        "start_engine",
        lambda names, *args, **kwargs: (None, ["winrt: Could not set default voice.", "sapi: no voices"]),
    )
    report = tmp_path / "report.txt"
    assert selfcheck.run(report) == 0, report.read_text(encoding="utf-8")
    line = next(
        line for line in report.read_text(encoding="utf-8").splitlines()
        if "text to speech" in line
    )
    assert line.startswith("ok") and "none started" in line and "sapi: no voices" in line
