import pytest
import requests

from wintranslate.translate import (
    FREE_PROVIDERS,
    MAX_INPUT_CHARS,
    EmptySelectionError,
    Engine,
    FreeProvider,
    ResponseParseError,
    SelectionTooLongError,
    ServiceError,
    Translator,
    parse_dict_chrome_response,
    parse_official_response,
    parse_single_response,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    """Stands in for requests.Session, recording every call it was asked to make.

    ``responses`` is consumed one per request, so a test can script a provider
    chain: first endpoint 429s, second answers.
    """

    def __init__(self, *responses):
        self.headers = {}
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self._responses.pop(0) if self._responses else _FakeResponse(None, 500)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestParseSingleResponse:
    """The shape used by client=at and client=gtx."""

    def test_joins_every_sentence_chunk(self):
        payload = [
            [["Xin chào. ", "Hello. ", None, None, 10],
             ["Tạm biệt.", "Goodbye.", None, None, 10]],
            None,
            "en",
        ]
        result = parse_single_response(payload)
        assert result.text == "Xin chào. Tạm biệt."
        assert result.detected_source == "en"

    def test_preserves_newlines_inside_chunks(self):
        payload = [[["Dòng đầu\n", "First line\n"], ["Dòng hai", "Second line"]], None, "en"]
        assert parse_single_response(payload).text == "Dòng đầu\nDòng hai"

    def test_missing_detected_language_is_not_fatal(self):
        result = parse_single_response([[["Xin chào", "Hello", None, None, 10]]])
        assert result.text == "Xin chào"
        assert result.detected_source is None

    def test_skips_malformed_chunks(self):
        payload = [[["Xin ", "Hi "], None, ["chào", "there"]], None, "en"]
        assert parse_single_response(payload).text == "Xin chào"

    def test_empty_chunk_list_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_single_response([[], None, "en"])

    def test_error_object_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_single_response({"error": "quota exceeded"})

    def test_empty_payload_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_single_response([])


class TestParseDictChromeResponse:
    """The shape used by clients5 / dict-chrome-ex."""

    def test_reads_text_and_detected_language(self):
        result = parse_dict_chrome_response([["Xin chào thế giới.", "en"]])
        assert result.text == "Xin chào thế giới."
        assert result.detected_source == "en"

    def test_multi_sentence_text_arrives_already_joined(self):
        payload = [["Con mèo ngồi. Trời đang mưa. Không ai đến.", "en"]]
        assert parse_dict_chrome_response(payload).text.count(".") == 3

    def test_preserves_newlines(self):
        payload = [["Dòng đầu\nDòng hai\nDòng ba", "en"]]
        assert parse_dict_chrome_response(payload).text.count("\n") == 2

    def test_missing_language_is_not_fatal(self):
        assert parse_dict_chrome_response([["Xin chào"]]).detected_source is None

    def test_empty_text_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_dict_chrome_response([["", "en"]])

    def test_empty_payload_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_dict_chrome_response([])

    def test_error_object_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_dict_chrome_response({"error": 429})


class TestParseOfficialResponse:
    def test_reads_the_first_translation(self):
        payload = {
            "data": {
                "translations": [
                    {"translatedText": "Xin chào", "detectedSourceLanguage": "en"}
                ]
            }
        }
        result = parse_official_response(payload)
        assert result.text == "Xin chào"
        assert result.detected_source == "en"

    def test_detected_language_is_optional(self):
        payload = {"data": {"translations": [{"translatedText": "Xin chào"}]}}
        assert parse_official_response(payload).detected_source is None

    def test_error_payload_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_official_response({"error": {"code": 403}})

    def test_empty_translation_list_is_rejected(self):
        with pytest.raises(ResponseParseError):
            parse_official_response({"data": {"translations": []}})


class TestEngineSelection:
    def test_defaults_to_the_free_endpoints(self):
        assert Translator().engine is Engine.FREE

    def test_an_api_key_switches_to_the_official_endpoint(self):
        assert Translator(api_key="abc123").engine is Engine.OFFICIAL

    def test_a_blank_api_key_is_treated_as_absent(self):
        translator = Translator(api_key="   ")
        assert translator.engine is Engine.FREE
        assert translator.api_key is None


class TestInputGuards:
    def test_rejects_an_empty_selection_without_calling_out(self):
        session = _FakeSession()
        with pytest.raises(EmptySelectionError):
            Translator(session=session).translate("   \n  ")
        assert session.calls == []

    def test_rejects_an_oversized_selection_without_calling_out(self):
        session = _FakeSession()
        with pytest.raises(SelectionTooLongError):
            Translator(session=session).translate("x" * (MAX_INPUT_CHARS + 1))
        assert session.calls == []


class TestProviderChain:
    def test_uses_the_first_provider_when_it_answers(self):
        session = _FakeSession(_FakeResponse([["Xin chào", "en"]]))
        result = Translator(session=session).translate("Hello")
        assert result.text == "Xin chào"
        assert len(session.calls) == 1, "a working first provider ends the chain"

    def test_falls_through_to_the_next_provider_on_429(self):
        session = _FakeSession(
            _FakeResponse(None, status_code=429),
            _FakeResponse([[["Xin chào", "Hello"]], None, "en"]),
        )
        result = Translator(session=session).translate("Hello")
        assert result.text == "Xin chào"
        assert len(session.calls) == 2

    def test_falls_through_on_403(self):
        session = _FakeSession(
            _FakeResponse(None, status_code=403),
            _FakeResponse([[["Xin chào", "Hello"]], None, "en"]),
        )
        assert Translator(session=session).translate("Hello").text == "Xin chào"

    def test_falls_through_on_a_connection_failure(self):
        session = _FakeSession(
            requests.ConnectionError("no route"),
            _FakeResponse([[["Xin chào", "Hello"]], None, "en"]),
        )
        assert Translator(session=session).translate("Hello").text == "Xin chào"

    def test_falls_through_on_an_unparseable_body(self):
        session = _FakeSession(
            _FakeResponse("<html>Sorry...</html>"),
            _FakeResponse([[["Xin chào", "Hello"]], None, "en"]),
        )
        assert Translator(session=session).translate("Hello").text == "Xin chào"

    def test_raises_the_last_error_when_every_provider_fails(self):
        session = _FakeSession(
            *[_FakeResponse(None, status_code=429) for _ in FREE_PROVIDERS]
        )
        with pytest.raises(ServiceError, match="429"):
            Translator(session=session).translate("Hello")
        assert len(session.calls) == len(FREE_PROVIDERS)

    def test_each_provider_targets_the_configured_language(self):
        session = _FakeSession(
            *[_FakeResponse(None, status_code=429) for _ in FREE_PROVIDERS]
        )
        with pytest.raises(ServiceError):
            Translator(target_language="ja", session=session).translate("Hello")
        assert all("tl=ja" in url for _, url, _ in session.calls)

    def test_every_request_carries_a_timeout(self):
        session = _FakeSession(_FakeResponse([["Xin chào", "en"]]))
        Translator(session=session).translate("Hello")
        assert all(kwargs["timeout"] == 10 for _, _, kwargs in session.calls)


class TestOfficialEngine:
    def test_sends_the_key_and_body(self):
        session = _FakeSession(
            _FakeResponse({"data": {"translations": [{"translatedText": "Xin chào"}]}})
        )
        translator = Translator(api_key="secret", session=session)
        assert translator.translate("Hello").text == "Xin chào"
        method, url, kwargs = session.calls[0]
        assert method == "POST"
        assert url.endswith("/language/translate/v2")
        assert kwargs["params"] == {"key": "secret"}
        assert kwargs["json"]["target"] == "vi"

    def test_does_not_fall_back_to_the_free_endpoints(self):
        session = _FakeSession(_FakeResponse(None, status_code=429))
        with pytest.raises(ServiceError):
            Translator(api_key="secret", session=session).translate("Hello")
        assert len(session.calls) == 1, "a paid key must not leak to unofficial hosts"


class TestCustomProviders:
    def test_a_single_provider_chain_is_honoured(self):
        provider = FreeProvider(
            "test", lambda text, target: "https://example.test/x", parse_dict_chrome_response
        )
        session = _FakeSession(_FakeResponse([["Xin chào", "en"]]))
        translator = Translator(session=session, providers=(provider,))
        assert translator.translate("Hello").text == "Xin chào"
        assert session.calls[0][1] == "https://example.test/x"
