"""Reading text aloud with the system's own voices.

QtTextToSpeech drives the platform engine: AVSpeechSynthesizer on macOS
(``darwin``), and the OneCore voices on Windows (``winrt``, with ``sapi`` as the
older fallback). Nothing leaves the machine, unlike Google's unofficial
``translate_tts`` endpoint, which would send every selection a second time.

Five behaviours of Qt Speech 6.11 shape this module. The first four were
measured with PySide6 6.11.2 on macOS; the rest of the list was read from the
engine sources, as noted.

* ``setLocale()`` with a locale the engine has no voice for fails silently and
  keeps the previous voice. Asking for ``km_KH`` while ``vi_VN`` was active left
  the Vietnamese voice in place, so Khmer would have been read by Linh. The
  locale is therefore chosen from ``availableLocales()`` before the call.
* ``darwin`` looks the voice up by ``QLocale.bcp47Name()``, which drops a
  language's default region: ``fr_FR`` becomes plain ``fr``, and macOS answered
  with Amélie (``fr_CA``) although a ``fr_FR`` voice is installed; ``nl_NL``
  got Ellen (``nl_BE``). So the locale the engine lands on is read back after
  ``setLocale()`` and checked as well (see ``acceptable``). Qt offers no other
  way to reach the ``fr_FR`` voice.
* ``darwin`` reports state changes late: ``say()`` returns while the state is
  still ``Ready`` and ``Speaking`` arrives a few milliseconds later; ``stop()``
  returns while it still says ``Speaking``. A caller that tracks who is
  speaking has to follow the signals, not read the state right after a call.
* ``darwin`` speaks only under the native platform plugin. Under the
  ``offscreen`` plugin the tests use, it lists its locales but never leaves
  ``Ready``, so the tests use the ``mock`` engine instead.
* From the sources: the darwin, winrt and sapi engines all return early from
  ``setError()`` for any real error, so ``errorOccurred`` never fires and a
  failed ``say()`` may report nothing at all. ``winrt`` starts in the ``Error``
  state and moves to ``Ready`` only when it found a default voice, which is how
  a failed start can be seen. It also synthesises the whole text before it
  starts to play, so ``Speaking`` can come seconds after ``say()``, and it
  plays to the audio output that was the default when it was created, for as
  long as it lives. sapi, finally, reports a state change only when a batch of
  events ends in a different state from the one it began in, so stopping one
  text and starting another in the same voice may report nothing at all.
"""

from __future__ import annotations

import html
import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QLocale, QObject, QSignalBlocker, Signal

log = logging.getLogger(__name__)

#: Forces one engine by name, for a machine where the default misbehaves and
#: for the tests, which set it to ``mock``. An engine that is not installed is
#: ignored and the normal choice applies.
ENGINE_ENV = "WIN_TRANSLATE_TTS_ENGINE"

#: Qt's test engine. Its voices are fake and it reads nothing aloud, so it is
#: only ever used when asked for by name.
MOCK_ENGINE = "mock"

#: Codes that Google or the app uses but QLocale spells differently. Google
#: still reports Hebrew as ``iw`` and Javanese as ``jw``; Qt files Tagalog under
#: Filipino and Norwegian under Bokmål. ``pt`` means Portugal in this app (see
#: languages.py), while QLocale reads a bare ``pt`` as Brazil.
_ALIASES: dict[str, tuple[str, str | None]] = {
    "iw": ("he", None),
    "jw": ("jv", None),
    "tl": ("fil", None),
    "no": ("nb", None),
    "pt": ("pt", "PT"),
}


def preferred_engines() -> tuple[str, ...]:
    """Engines to try, best first, for this platform."""
    if sys.platform == "win32":
        # winrt sees the OneCore voices, which is where Windows installs the
        # ones a user adds in Settings -- the only Vietnamese voice ("An")
        # among them. sapi sees only the older desktop voices.
        return ("winrt", "sapi")
    if sys.platform == "darwin":
        return ("darwin",)
    return ("speechd", "flite")


def available_engines() -> list[str]:
    """Every engine plugin Qt can load, the mock one included."""
    from PySide6.QtTextToSpeech import QTextToSpeech

    return list(QTextToSpeech.availableEngines())


def engine_candidates(available: list[str], forced: str | None = None) -> list[str]:
    """Engine names from ``available`` to try, best first.

    ``forced`` comes first when it is installed, ``mock`` included. Then the
    platform's preferred engines, then any other engine that is not the mock.
    """
    order: list[str] = []
    if forced and forced in available:
        order.append(forced)
    order += [name for name in preferred_engines() if name in available]
    order += [name for name in available if name != MOCK_ENGINE]
    return list(dict.fromkeys(order))


def default_audio_output() -> bytes:
    """The id of the system's default audio output, empty when there is none.

    Only called for winrt, on Windows, where the build keeps Qt Multimedia;
    the macOS build leaves it out.
    """
    from PySide6.QtMultimedia import QMediaDevices

    device = QMediaDevices.defaultAudioOutput()
    return b"" if device.isNull() else bytes(device.id())


def _create_engine(name: str, parent: QObject | None):
    from PySide6.QtTextToSpeech import QTextToSpeech

    return QTextToSpeech(name, parent)


def start_engine(
    names: list[str],
    parent: QObject | None = None,
    create: Callable[[str, QObject | None], object] | None = None,
):
    """Start the first engine in ``names`` that works.

    An engine works when it did not start in the ``Error`` state and has at
    least one voice. On Windows that is what lets sapi take over when winrt
    found no OneCore voice. Returns the engine (or None) and one line per
    engine that was passed over, saying why.
    """
    from PySide6.QtTextToSpeech import QTextToSpeech

    create = create or _create_engine
    passed_over: list[str] = []
    for name in names:
        engine = create(name, parent)
        if engine.state() == QTextToSpeech.State.Error:
            passed_over.append(f"{name}: {engine.errorString() or 'failed to start'}")
        elif not engine.availableLocales():
            passed_over.append(f"{name}: no voices")
        else:
            return engine, passed_over
        engine.deleteLater()
    return None, passed_over


def requested_locale(code: str | None) -> tuple[QLocale, bool] | None:
    """The locale a language code asks for, and whether its region is binding.

    The region is binding when the code itself names one (``zh-TW``): a voice
    for another region could be another language altogether, such as Cantonese
    for Taiwanese Mandarin. A bare code (``en``, ``sw``) only states a
    preference, and any voice for that language and script will do.

    Returns None for a code QLocale does not know, such as ``hmn`` or ``auto``.
    """
    if not code:
        return None
    language, _, region = code.strip().replace("_", "-").partition("-")
    language = language.lower()
    binding = bool(region)
    alias, alias_region = _ALIASES.get(language, (language, None))
    region = region.upper() or (alias_region or "")
    locale = QLocale(f"{alias}_{region}" if region else alias)
    if locale.language() in (QLocale.Language.C, QLocale.Language.AnyLanguage):
        return None
    return locale, binding


def acceptable(code: str | None, candidate: QLocale) -> bool:
    """Whether a voice for ``candidate`` may read text in ``code``.

    Same language and script, always; same region too when the code names one.
    """
    wanted = requested_locale(code)
    if wanted is None:
        return False
    locale, binding = wanted
    return (
        candidate.language() == locale.language()
        and candidate.script() == locale.script()
        and (not binding or candidate.territory() == locale.territory())
    )


def match_locale(code: str | None, available: list[QLocale]) -> QLocale | None:
    """The locale from ``available`` to ask the engine for, to read ``code``.

    Only a locale taken from ``available`` is returned: a locale the engine did
    not list is one ``setLocale()`` may ignore without a word.
    """
    wanted = requested_locale(code)
    if wanted is None:
        return None
    locale, _ = wanted
    fits = [candidate for candidate in available if acceptable(code, candidate)]
    for candidate in fits:
        if candidate.territory() == locale.territory():
            return candidate
    # Sorted so the same machine always picks the same voice.
    return sorted(fits, key=QLocale.name)[0] if fits else None


@dataclass(frozen=True)
class Voice:
    """The voice that would read a language: where the engine landed."""

    #: The locale to pass to setLocale(), one the engine listed.
    asked: QLocale
    #: The locale the engine reported afterwards. On macOS it can differ from
    #: ``asked`` in its region; see the module docstring.
    landed: QLocale
    name: str


class Speaker(QObject):
    """One lazily created text-to-speech engine, shared by the popup's buttons.

    ``speaking`` and ``stopped`` follow the engine's own signals, so a listener
    sees the real state even on an engine that reports it late.
    """

    speaking = Signal()
    stopped = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        create: Callable[[str, QObject | None], object] | None = None,
    ) -> None:
        super().__init__(parent)
        #: Builds an engine by name; the tests pass a fake.
        self._create = create
        self._engine = None
        self._engine_failed = False
        #: Engines that were tried and passed over, for reports.
        self.passed_over: list[str] = []
        #: The engine's locales, listed once: on macOS each call takes ~50 ms.
        self._locales: list[QLocale] = []
        self._voices: dict[str, Voice | None] = {}
        #: For winrt, the default audio output when the engine was created.
        self._audio_output: bytes | None = None

    # -- engine -------------------------------------------------------------

    def _tts(self):
        """The engine, created on first use. Creating it and listing its
        locales took ~150 ms on macOS, on the GUI thread; see prepare()."""
        if self._engine is not None or self._engine_failed:
            return self._engine
        names = engine_candidates(available_engines(), os.environ.get(ENGINE_ENV))
        engine, self.passed_over = start_engine(names, self, self._create)
        for line in self.passed_over:
            log.warning("Text-to-speech engine passed over: %s", line)
        if engine is None:
            log.info("No text-to-speech engine is available (tried: %s)", names or "none")
            self._engine_failed = True
            return None
        engine.stateChanged.connect(self._on_state)
        engine.errorOccurred.connect(self._on_error)
        self._locales = list(engine.availableLocales())
        log.info("Text-to-speech engine: %s, %d locales", engine.engine(), len(self._locales))
        if engine.engine() == "winrt":
            self._audio_output = default_audio_output()
        self._engine = engine
        return engine

    def _follow_audio_output(self) -> None:
        """Start the engine again if winrt would play to a stale output.

        winrt keeps the output that was the default when it was created; the
        engine is created a few seconds after launch, and an app that starts
        at login would otherwise read to the laptop speakers after headphones
        were plugged in, or to nothing after a headset was unplugged.
        """
        engine = self._engine
        if engine is None or engine.engine() != "winrt":
            return
        if default_audio_output() == self._audio_output:
            return
        log.info("The default audio output changed; starting the speech engine again")
        engine.stateChanged.disconnect(self._on_state)
        engine.errorOccurred.disconnect(self._on_error)
        engine.stop()
        engine.deleteLater()
        self._engine = None
        self._audio_output = None
        self._locales = []
        self._voices = {}
        self._tts()

    def prepare(self) -> None:
        """Create the engine now, so the first translation does not wait for it."""
        self._tts()

    @property
    def engine_name(self) -> str | None:
        engine = self._tts()
        return engine.engine() if engine is not None else None

    def is_available(self) -> bool:
        return self._tts() is not None

    def _set_locale(self, locale: QLocale) -> QLocale:
        """Ask for ``locale`` and return the one the engine landed on.

        Signals are held back: sapi reports Ready from inside setLocale(), and
        this is a lookup, not a change anyone listening needs to hear about.
        """
        engine = self._engine
        blocker = QSignalBlocker(engine)
        try:
            if engine.locale() != locale:
                engine.setLocale(locale)
            return engine.locale()
        finally:
            blocker.unblock()

    def voice_for(self, code: str | None) -> Voice | None:
        """The voice that would read ``code``, or None when the engine has no
        voice for that language.

        The engine's default voice for the locale is what reads it. Picking
        from ``availableVoices()`` instead can land on a novelty voice: macOS
        lists "Bad News" and "Bubbles" among its English ones.
        """
        if not code:
            return None
        key = code.lower()
        if key not in self._voices:
            self._voices[key] = self._find_voice(code)
        # Cached for the life of the app, so a voice installed while it runs
        # is picked up after a restart.
        return self._voices[key]

    def _find_voice(self, code: str) -> Voice | None:
        if self._tts() is None:
            return None
        asked = match_locale(code, self._locales)
        if asked is None:
            return None
        landed = self._set_locale(asked)
        if not acceptable(code, landed):
            log.info(
                "No voice for %s: asked for %s, the engine landed on %s",
                code,
                asked.name(),
                landed.name(),
            )
            return None
        return Voice(asked, landed, self._engine.voice().name())

    # -- speaking -----------------------------------------------------------

    def say(self, text: str, code: str | None) -> bool:
        """Read ``text`` in the voice for ``code``. Returns False when there is
        no voice for it, in which case nothing is read."""
        self._follow_audio_output()
        voice = self.voice_for(code)
        engine = self._tts()
        if voice is None or engine is None or not text.strip():
            return False
        engine.stop()
        landed = self._set_locale(voice.asked)
        if landed != voice.landed:
            # The engine moved since the voice was looked up; never read with
            # whatever it moved to.
            log.warning("Not reading %s: the engine landed on %s", code, landed.name())
            return False
        if engine.engine() == "sapi":
            # Qt puts an XML tag in front of the text, so SAPI parses all of it
            # as XML: "Tom & Jerry" or "a < b" would break or be read as markup.
            text = html.escape(text, quote=False)
        engine.say(text)
        return True

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    def is_speaking(self) -> bool:
        """What the engine says now. Late on darwin right after a call (see
        the module docstring), but settled a few seconds on."""
        from PySide6.QtTextToSpeech import QTextToSpeech

        engine = self._engine
        return engine is not None and engine.state() in (
            QTextToSpeech.State.Speaking,
            QTextToSpeech.State.Synthesizing,
        )

    def set_volume(self, volume: float) -> None:
        """0.0 to 1.0. The app never calls it and keeps the system volume;
        the speak test uses it to run silently."""
        engine = self._tts()
        if engine is not None:
            engine.setVolume(volume)

    @property
    def voice_name(self) -> str:
        """The voice the engine would read with now, for reports."""
        engine = self._tts()
        return engine.voice().name() if engine is not None else ""

    def last_error(self) -> str:
        """The engine's own account of its last error, for reports and logs.

        Qt 6.11's engines record an error here even when they do not signal it.
        """
        engine = self._engine
        if engine is None:
            return ""
        reason = engine.errorReason()
        if reason.name == "NoError":
            return ""
        return f"{reason.name}: {engine.errorString()}"

    def _on_state(self, state) -> None:
        from PySide6.QtTextToSpeech import QTextToSpeech

        if state in (QTextToSpeech.State.Speaking, QTextToSpeech.State.Synthesizing):
            self.speaking.emit()
        else:
            self.stopped.emit()

    def _on_error(self, reason, message: str) -> None:
        # Unreachable with Qt 6.11's engines (see the module docstring); kept
        # for a Qt that signals its errors.
        log.warning("Text-to-speech error %s: %s", reason, message)
        self.stopped.emit()
