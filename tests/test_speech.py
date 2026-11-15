"""Choosing an engine and a voice.

The rule these guard: never read one language with another language's voice.
setLocale() with a locale the engine has no voice for keeps the previous voice
without a word, so a wrong match here means Khmer read aloud by the Vietnamese
voice, not an error anyone would see.
"""

import sys

import pytest
from PySide6.QtCore import QLocale, QObject, Signal

from wintranslate import speech
from wintranslate.speech import engine_candidates, match_locale, requested_locale, start_engine


def locales(*names: str) -> list[QLocale]:
    return [QLocale(name) for name in names]


def matched(code, *available: str) -> str | None:
    found = match_locale(code, locales(*available))
    return found.name() if found is not None else None


class TestMatchLocale:
    def test_a_bare_code_prefers_its_usual_region(self):
        assert matched("en", "en_GB", "en_US", "en_AU") == "en_US"
        assert matched("fr", "fr_CA", "fr_FR") == "fr_FR"

    def test_a_bare_code_takes_another_region_of_the_same_language(self):
        # macOS files Arabic under the world region (ar_001), not Egypt.
        assert matched("ar", "ar_001") == "ar_001"
        assert matched("pt", "pt_BR") == "pt_BR"

    def test_pt_means_portugal_when_both_are_there(self):
        assert matched("pt", "pt_BR", "pt_PT") == "pt_PT"

    def test_a_region_in_the_code_is_binding(self):
        # Same language, different territory: no match, not the nearest one.
        assert matched("en-AU", "en_GB", "en_US") is None
        assert matched("pt-BR", "pt_PT") is None

    def test_traditional_chinese_is_never_read_as_simplified(self):
        assert matched("zh-TW", "zh_CN") is None
        assert matched("zh-TW", "zh_CN", "zh_TW") == "zh_TW"
        assert matched("zh-CN", "zh_TW", "zh_HK") is None

    def test_a_bare_zh_does_not_cross_scripts(self):
        # zh_HK is Cantonese in traditional script; a bare zh is simplified.
        assert matched("zh", "zh_TW", "zh_HK") is None
        assert matched("zh", "zh_HK", "zh_CN") == "zh_CN"

    @pytest.mark.parametrize(
        "code, available, expected",
        [
            ("iw", "he_IL", "he_IL"),
            ("jw", "jv_ID", "jv_ID"),
            ("tl", "fil_PH", "fil_PH"),
            ("no", "nb_NO", "nb_NO"),
        ],
    )
    def test_googles_old_codes_find_their_voices(self, code, available, expected):
        assert matched(code, available) == expected

    def test_a_language_with_no_voice_gets_none(self):
        assert matched("km", "vi_VN", "en_US") is None
        assert matched("vi", "en_GB", "en_US", "fi_FI", "nb_NO", "nn_NO") is None

    @pytest.mark.parametrize("code", ["", None, "auto", "hmn", "xx"])
    def test_codes_qt_does_not_know_get_none(self, code):
        assert requested_locale(code) is None
        assert matched(code, "en_US", "vi_VN") is None

    def test_the_match_is_one_of_the_engines_own_locales(self):
        """Only a locale the engine listed is known to be honoured."""
        available = locales("en_GB", "en_US")
        assert match_locale("en", available) in available

    def test_casing_and_underscores_do_not_matter(self):
        assert matched("ZH-tw", "zh_TW") == "zh_TW"
        assert matched("zh_TW", "zh_TW") == "zh_TW"


class TestEngineCandidates:
    def test_the_mock_engine_is_never_a_candidate_on_its_own(self):
        assert engine_candidates(["mock"]) == []
        assert engine_candidates([]) == []

    def test_a_forced_engine_comes_first_when_it_is_installed(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert engine_candidates(["darwin", "mock"], forced="mock") == ["mock", "darwin"]

    def test_a_forced_engine_that_is_missing_is_ignored(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert engine_candidates(["darwin", "mock"], forced="sapi") == ["darwin"]

    def test_windows_tries_winrt_then_sapi(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert engine_candidates(["mock", "sapi", "winrt"]) == ["winrt", "sapi"]
        assert engine_candidates(["mock", "sapi"]) == ["sapi"]

    def test_an_unknown_real_engine_is_still_tried(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert engine_candidates(["mock", "flite"]) == ["flite"]


class FakeEngine(QObject):
    """A QTextToSpeech stand-in for what the mock engine cannot do: fail to
    start, have no voices, or land on another region the way darwin does."""

    stateChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self, name, *, failed=False, locales=("fr_FR", "fr_CA", "zh_CN", "en_US"),
                 lands=None, parent=None):
        super().__init__(parent)
        from PySide6.QtTextToSpeech import QTextToSpeech

        self._name = name
        self._state = QTextToSpeech.State.Error if failed else QTextToSpeech.State.Ready
        self._locales = [QLocale(name) for name in locales]
        #: setLocale(asked) lands on lands[asked], like darwin's bcp47 lookup.
        self._lands = lands or {}
        # Starts somewhere no test asks for, so every lookup calls setLocale().
        self._locale = QLocale("ja_JP")
        self.said: list[str] = []
        self.deleted = False

    def engine(self):
        return self._name

    def state(self):
        return self._state

    def errorString(self):
        return "Could not set default voice." if self._state.name == "Error" else ""

    def errorReason(self):
        from PySide6.QtTextToSpeech import QTextToSpeech

        return QTextToSpeech.ErrorReason.NoError

    def availableLocales(self):
        return list(self._locales)

    def locale(self):
        return self._locale

    def setLocale(self, locale):
        self._locale = QLocale(self._lands.get(locale.name(), locale.name()))
        self.stateChanged.emit(self._state)  # sapi reports Ready from in here

    def voice(self):
        engine = self

        class _Voice:
            def name(self):
                return f"voice-{engine._locale.name()}"

        return _Voice()

    def say(self, text):
        self.said.append(text)

    def stop(self):
        pass

    def setVolume(self, volume):
        pass

    def deleteLater(self):
        self.deleted = True


def factory(**per_engine):
    """A create() for start_engine/Speaker: per_engine maps a name to the
    FakeEngine keyword arguments for it."""
    made = {}

    def create(name, parent):
        made[name] = FakeEngine(name, parent=parent, **per_engine.get(name, {}))
        return made[name]

    create.made = made
    return create


class TestStartEngine:
    def test_winrt_failing_to_start_falls_back_to_sapi(self):
        create = factory(winrt={"failed": True})
        engine, passed_over = start_engine(["winrt", "sapi"], create=create)
        assert engine.engine() == "sapi"
        assert passed_over == ["winrt: Could not set default voice."]
        assert create.made["winrt"].deleted

    def test_an_engine_with_no_voices_is_passed_over(self):
        create = factory(winrt={"locales": ()})
        engine, passed_over = start_engine(["winrt", "sapi"], create=create)
        assert engine.engine() == "sapi"
        assert passed_over == ["winrt: no voices"]

    def test_none_starting_gives_none_and_says_why(self):
        create = factory(winrt={"failed": True}, sapi={"locales": ()})
        engine, passed_over = start_engine(["winrt", "sapi"], create=create)
        assert engine is None
        assert len(passed_over) == 2

    def test_the_speaker_uses_the_fallback(self, qapp, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["mock", "sapi", "winrt"])
        speaker = speech.Speaker(create=factory(winrt={"failed": True}))
        assert speaker.engine_name == "sapi"
        assert speaker.passed_over == ["winrt: Could not set default voice."]


class TestWhereTheEngineLands:
    """darwin looks voices up by bcp47Name(), which drops a default region:
    asking for fr_FR got Amélie (fr_CA) on a Mac that has a fr_FR voice."""

    @pytest.fixture
    def darwin_like(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["darwin"])

        def make(lands):
            return speech.Speaker(create=factory(darwin={"lands": lands}))

        return make

    def test_a_bare_code_accepts_another_region_of_its_language(self, qapp, darwin_like):
        speaker = darwin_like({"fr_FR": "fr_CA"})
        voice = speaker.voice_for("fr")
        assert voice is not None
        assert (voice.asked.name(), voice.landed.name()) == ("fr_FR", "fr_CA")
        assert voice.name == "voice-fr_CA", "the tooltip names the voice that reads"
        assert speaker.say("Bonjour", "fr"), "and that voice does read"
        assert speaker._engine.said == ["Bonjour"]

    def test_a_region_in_the_code_must_be_where_it_lands(self, qapp, darwin_like):
        speaker = darwin_like({"zh_CN": "zh_TW"})
        assert speaker.voice_for("zh-CN") is None
        assert not speaker.say("你好", "zh-CN")

    def test_landing_on_another_language_is_refused(self, qapp, darwin_like):
        speaker = darwin_like({"en_US": "fr_CA"})
        assert speaker.voice_for("en") is None

    def test_say_refuses_when_the_engine_moves_after_the_lookup(self, qapp, darwin_like):
        speaker = darwin_like({})
        assert speaker.voice_for("fr") is not None
        speaker._engine._lands["fr_FR"] = "fr_CA"
        speaker._engine._locale = QLocale("ja_JP")
        assert not speaker.say("Bonjour", "fr")
        assert speaker._engine.said == []

    def test_the_lookup_does_not_leak_engine_signals(self, qapp, darwin_like):
        """sapi reports Ready from inside setLocale(); a lookup made while the
        popup refreshes its buttons must not call back into the popup."""
        speaker = darwin_like({})
        heard = []
        speaker.stopped.connect(lambda: heard.append("stopped"))
        speaker.voice_for("fr")
        assert heard == []


class TestWinrtAudioOutput:
    """winrt plays to the output that was the default when it was created."""

    @pytest.fixture
    def winrt(self, qapp, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["winrt", "sapi"])
        output = {"id": b"speakers"}
        monkeypatch.setattr(speech, "default_audio_output", lambda: output["id"])
        create = factory(winrt={"locales": ("en_US",)})
        return speech.Speaker(create=create), create, output

    def test_a_new_default_output_gets_a_new_engine(self, winrt):
        speaker, create, output = winrt
        speaker.prepare()
        first = speaker._engine
        output["id"] = b"headset"
        assert speaker.say("Hello", "en")
        assert speaker._engine is not first
        assert first.deleted
        assert speaker._engine.said == ["Hello"]

    def test_the_same_output_keeps_the_engine(self, winrt):
        speaker, create, output = winrt
        speaker.prepare()
        first = speaker._engine
        assert speaker.say("Hello", "en")
        assert speaker.say("Again", "en")
        assert speaker._engine is first

    def test_the_old_engine_can_no_longer_reach_the_popup(self, winrt):
        speaker, create, output = winrt
        speaker.prepare()
        first = speaker._engine
        output["id"] = b""  # the headset was unplugged
        speaker.say("Hello", "en")
        heard = []
        speaker.stopped.connect(lambda: heard.append("stopped"))
        first.stateChanged.emit(first.state())
        assert heard == []


class TestSapiText:
    def test_markup_characters_are_escaped_for_sapi(self, qapp, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["sapi"])
        speaker = speech.Speaker(create=factory(sapi={"locales": ("en_US",)}))
        assert speaker.say("Tom & Jerry say a < b > c", "en")
        assert speaker._engine.said == ["Tom &amp; Jerry say a &lt; b &gt; c"]

    def test_other_engines_get_the_text_as_it_is(self, qapp, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["darwin"])
        speaker = speech.Speaker(create=factory(darwin={"locales": ("en_US",)}))
        assert speaker.say("Tom & Jerry", "en")
        assert speaker._engine.said == ["Tom & Jerry"]


def wait_for(qapp, condition, timeout: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    return condition()


class TestSpeakerWithTheMockEngine:
    """conftest forces the mock engine: five locales, no Vietnamese."""

    @pytest.fixture
    def speaker(self, qapp):
        return speech.Speaker()

    def test_uses_the_forced_engine(self, speaker):
        assert speaker.engine_name == "mock"

    def test_finds_voices_for_the_mock_locales_only(self, speaker):
        assert speaker.voice_for("en").landed.name() == "en_US"
        assert speaker.voice_for("no").landed.name() == "nb_NO"
        assert speaker.voice_for("vi") is None

    def test_reads_and_reports_start_and_end(self, speaker, qapp):
        events = []
        speaker.speaking.connect(lambda: events.append("speaking"))
        speaker.stopped.connect(lambda: events.append("stopped"))
        assert speaker.say("Hello there.", "en")
        assert wait_for(qapp, lambda: events[-1:] == ["stopped"] and "speaking" in events)

    def test_refuses_a_language_it_has_no_voice_for(self, speaker):
        assert not speaker.say("Xin chào", "vi")

    def test_refuses_blank_text(self, speaker):
        assert not speaker.say("   ", "en")

    def test_switches_voice_between_languages(self, speaker):
        engine = speaker._tts()
        speaker.say("Hei", "fi")
        assert engine.locale().name() == "fi_FI"
        speaker.say("Hello", "en")
        assert engine.locale().name() == "en_US"
        speaker.stop()


    def test_stop_silences_the_engine(self, speaker):
        from PySide6.QtTextToSpeech import QTextToSpeech

        assert speaker.say("one two three four five six seven eight nine ten", "en")
        assert speaker._engine.state() == QTextToSpeech.State.Speaking
        assert speaker.is_speaking()
        speaker.stop()
        assert speaker._engine.state() == QTextToSpeech.State.Ready
        assert not speaker.is_speaking()


class TestSpeakerWithoutAnEngine:
    def test_nothing_is_available_and_nothing_breaks(self, qapp, monkeypatch):
        monkeypatch.delenv(speech.ENGINE_ENV, raising=False)
        monkeypatch.setattr(speech, "available_engines", lambda: ["mock"])
        speaker = speech.Speaker()
        assert not speaker.is_available()
        assert speaker.engine_name is None
        assert speaker.voice_for("en") is None
        assert not speaker.say("Hello", "en")
        speaker.stop()


class TestPrepare:
    def test_prepare_starts_the_engine_before_anything_is_read(self, qapp):
        speaker = speech.Speaker()
        assert speaker._engine is None, "nothing is started at construction"
        speaker.prepare()
        assert speaker._engine is not None
        assert speaker._locales, "the locales are listed once, up front"
