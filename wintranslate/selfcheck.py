"""A quick check that a packaged build carries everything it needs.

Run as ``win-translate --self-check REPORT``. It touches each piece a frozen
build can silently lose -- a platform module, a Qt plugin, a data file, the CA
bundle for HTTPS -- without showing a window, registering a hotkey or using the
network. Findings go to REPORT, because a windowed .exe has no console, and the
exit status is non-zero when anything is missing, so a release build can stop
before it ships a broken app.

``win-translate --speak-test REPORT [CODE [VOLUME]]`` is the one check that
makes a sound: it reads a sentence aloud through the same path as the popup's
speaker buttons. It is for a person at a real machine -- a CI runner may have
no audio device -- and it is how to hear the frozen app rather than the venv.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

#: Library names that mean FFmpeg was bundled. Qt Multimedia's FFmpeg backend
#: plays media files; the speech engines do not use it.
_FFMPEG_LIBRARIES = ("avcodec", "avformat", "avutil", "swresample", "swscale")


def run(report: Path) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841 - widgets need it
    lines: list[str] = []
    failures = 0

    def check(name: str, probe: Callable[[], str]) -> None:
        nonlocal failures
        try:
            lines.append(f"ok   {name}: {probe()}")
        except Exception as exc:  # noqa: BLE001 - every failure is reported and counted
            failures += 1
            lines.append(f"FAIL {name}: {type(exc).__name__}: {exc}")

    check("qt platform", lambda: QApplication.platformName())
    check("platform modules", _platform_modules)
    check("icon", _icon)
    check("flag svg", _flag)
    check("theme assets", _theme_assets)
    check("svg image plugin", _svg_image_plugin)
    check("popup", _popup)
    check("settings window", _settings)
    check("https ca bundle", _ca_bundle)
    check("languages", _languages)
    check("text to speech", _text_to_speech)
    if getattr(sys, "frozen", False):
        check("lean bundle", _lean_bundle)

    lines.append(f"{failures} failure(s)")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


def _platform_modules() -> str:
    if sys.platform == "darwin":
        from wintranslate import hotkey_macos, macos, selection_macos  # noqa: F401

        return "hotkey_macos, selection_macos (AppKit, Quartz, ApplicationServices), macos"
    from wintranslate import hotkey, selection  # noqa: F401

    return "hotkey, selection"


def _icon() -> str:
    from wintranslate.app import draw_icon

    image = draw_icon(64).toImage()
    if image.isNull() or image.pixelColor(32, 4).alpha() == 0:
        raise RuntimeError("the icon came out empty")
    return "drawn"


def _flag() -> str:
    from wintranslate import flags

    path = flags.FLAG_DIR / "vn.svg"
    if not path.is_file():
        raise FileNotFoundError(path)
    # _render_svg returns None when Qt cannot read SVG -- the missing-plugin case
    # the list would otherwise hide behind blank placeholders.
    pixmap = flags._render_svg(path)
    if pixmap is None:
        raise RuntimeError(f"Qt could not render {path.name}")
    image = pixmap.toImage()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)
    if centre.alpha() == 0:
        raise RuntimeError(f"{path.name} rendered transparent")
    return f"{len(flags.available())} flags, {path.name} renders"


def _theme_assets() -> str:
    from wintranslate import theme

    missing = [
        name
        for name in ("chevron-down-dim.svg", "chevron-up-light.svg")
        if not (theme.ASSETS / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    return str(theme.ASSETS)


def _svg_image_plugin() -> str:
    # The stylesheet's chevrons load through Qt's image plugins, unlike the
    # flags, which QSvgRenderer draws directly; a build missing the plugin
    # passes the flag check and still shows no arrows.
    from PySide6.QtGui import QImageReader, QPixmap

    from wintranslate import theme

    if b"svg" not in [bytes(f) for f in QImageReader.supportedImageFormats()]:
        raise RuntimeError("Qt has no svg image format plugin")
    chevron = theme.ASSETS / "chevron-down-dim.svg"
    if QPixmap(str(chevron)).isNull():
        raise RuntimeError(f"QPixmap could not load {chevron.name}")
    return "svg"


def _popup() -> str:
    from wintranslate.popup import TranslationPopup

    popup = TranslationPopup()
    popup.deleteLater()
    return "built"


def _settings() -> str:
    from wintranslate.config import Config
    from wintranslate.settings import SettingsDialog

    dialog = SettingsDialog(Config(), lambda config: None)
    dialog.deleteLater()
    return "built"


def _ca_bundle() -> str:
    import requests.certs

    where = Path(requests.certs.where())
    if not where.is_file():
        raise FileNotFoundError(where)
    return where.name


def _languages() -> str:
    from wintranslate.languages import LANGUAGES

    if not LANGUAGES:
        raise RuntimeError("no languages")
    return f"{len(LANGUAGES)} languages"


def _text_to_speech() -> str:
    """A real speech engine plugin is bundled, and which one starts here.

    Fails only for what packaging controls: no engine plugin besides Qt's mock
    one. An engine that is bundled but finds no voice or no audio device on
    this machine -- a CI runner, say -- is reported, not failed.
    """
    from wintranslate import speech

    engines = speech.available_engines()
    # Not the WIN_TRANSLATE_TTS_ENGINE override: this checks what the app
    # would pick on its own, and it never picks the mock engine.
    names = speech.engine_candidates(engines)
    if not names:
        raise RuntimeError(
            f"no text-to-speech engine other than Qt's mock one (found: {engines or 'none'})"
        )
    engine, passed_over = speech.start_engine(names)
    notes = "".join(f"; {line}" for line in passed_over)
    if engine is None:
        return f"plugins {', '.join(names)}; none started on this machine{notes}"
    try:
        locales = list(engine.availableLocales())
        name = engine.engine()
        vietnamese = speech.match_locale("vi", locales)
        voice = "no voice"
        if vietnamese is not None:
            engine.setLocale(vietnamese)
            voice = f"{engine.voice().name() or 'unnamed voice'} ({engine.locale().name()})"
        return f"{name}, {len(locales)} locales, Vietnamese: {voice}{notes}"
    finally:
        engine.deleteLater()


def _lean_bundle() -> str:
    """The frozen app carries neither FFmpeg nor Qt's mock speech engine.

    Both come in with QtTextToSpeech's dependencies and packaging/
    win-translate.spec removes them; this catches a hook update that brings
    them back.
    """
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    found = sorted(
        path.name
        for path in root.rglob("*")
        if path.is_file()
        and (
            any(library in path.name.lower() for library in _FFMPEG_LIBRARIES)
            or "ffmpegmediaplugin" in path.name.lower()
            or "qtexttospeech_mock" in path.name.lower()
        )
    )
    if found:
        raise RuntimeError("bundled but unused: " + ", ".join(found))
    return "no FFmpeg, no mock speech engine"


def speak_test(report: Path, code: str = "vi", volume: float | None = None) -> int:
    """Read one sentence aloud in ``code`` and record what the engine did.

    Exits 0 once the engine has started speaking and then finished. Whether the
    sentence was audible, and in the right voice, is for the person running it
    to judge.
    """
    from PySide6.QtWidgets import QApplication

    from wintranslate.speech import Speaker

    app = QApplication.instance() or QApplication([])
    sentences = {
        "vi": "Xin chào, đây là bài kiểm tra giọng đọc của win-translate.",
        "en": "Hello, this is the win-translate speech test.",
    }
    text = sentences.get(code.split("-")[0].lower(), sentences["en"])
    speaker = Speaker()
    lines = [f"engine: {speaker.engine_name or 'none'}"]
    lines += [f"passed over: {line}" for line in speaker.passed_over]
    voice = speaker.voice_for(code)
    if voice is not None:
        lines.append(
            f"voice for {code}: {voice.name}, asked for {voice.asked.name()}, "
            f"landed on {voice.landed.name()}"
        )
    else:
        lines.append(f"voice for {code}: none")
    if volume is not None:
        speaker.set_volume(volume)

    started = time.monotonic()
    seen = {"speaking": False, "finished": False}

    def note(event: str) -> None:
        lines.append(f"{(time.monotonic() - started) * 1000:7.0f} ms  {event}")
        if event == "speaking":
            seen["speaking"] = True
        elif seen["speaking"]:
            seen["finished"] = True

    speaker.speaking.connect(lambda: note("speaking"))
    speaker.stopped.connect(lambda: note("stopped"))
    if not speaker.say(text, code):
        lines.append("FAIL nothing to read with: no engine, or no voice for this language")
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    lines.append(f"reading with: {speaker.voice_name}")
    deadline = started + 30
    while not seen["finished"] and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    ok = seen["speaking"] and seen["finished"]
    # Qt 6.11's engines record errors without signalling them; this is the
    # only place a failed playback leaves a trace.
    if speaker.last_error():
        lines.append(f"engine error: {speaker.last_error()}")
    lines.append("ok   spoke and finished" if ok else "FAIL did not speak and finish within 30 s")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1
