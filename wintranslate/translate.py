"""Google Translate client.

Two backends are supported:

* **Free** — the undocumented endpoints behind the Google Translate web widget
  and the Chrome dictionary extension. No API key, which is why it is the
  default, but Google rate-limits them per source IP and may change them without
  notice. Several are tried in order, because in practice one host answering 429
  says nothing about the next: on the network this was written on,
  ``translate.googleapis.com`` was throttled while ``clients5.google.com``
  answered fine.
* **Official** — Cloud Translation API v2, which needs an API key and billing
  enabled on the GCP project. Set ``google_api_key`` in the config to use it;
  it then becomes the only endpoint tried.

Response shapes differ between the free endpoints, so each carries its own
parser. Both were verified against the live services rather than guessed.
"""

from __future__ import annotations

import enum
import logging
import urllib.parse
from dataclasses import dataclass, replace
from typing import Callable

import requests

log = logging.getLogger(__name__)

# Every outbound call gets a timeout; a hung request would otherwise leave the
# popup spinning forever with no way for the user to tell why.
REQUEST_TIMEOUT_SECONDS = 10

# Google rejects very long `q` parameters on the free endpoints, and a selection
# that large is a mis-click rather than something anyone wants translated.
MAX_INPUT_CHARS = 5000

# The free endpoints answer 403 to clients that look automated.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class TranslateError(Exception):
    """Base class for every failure this module reports."""


class EmptySelectionError(TranslateError):
    def __init__(self) -> None:
        super().__init__("Không có text nào được bôi đen.")


class SelectionTooLongError(TranslateError):
    def __init__(self, length: int) -> None:
        super().__init__(
            f"Đoạn text dài {length:,} ký tự, vượt giới hạn {MAX_INPUT_CHARS:,}."
        )


class ServiceError(TranslateError):
    """The translation service could not be reached, or refused the request."""


class ResponseParseError(TranslateError):
    def __init__(self, detail: str = "") -> None:
        message = "Không đọc được kết quả trả về từ Google Translate."
        super().__init__(f"{message} {detail}".strip())


class Engine(enum.Enum):
    FREE = "free"
    OFFICIAL = "official"


@dataclass(frozen=True)
class Translation:
    text: str
    #: Language Google detected on the input, e.g. ``"en"``. ``None`` when the
    #: response did not carry one.
    detected_source: str | None
    #: Language the text was translated *into*. Set by the caller rather than the
    #: parsers, which only see the response body.
    target: str = ""


@dataclass(frozen=True)
class FreeProvider:
    """One unofficial endpoint, with the parser for its particular reply shape."""

    name: str
    build_url: Callable[[str, str], str]
    parse: Callable[[object], Translation]


def _dict_chrome_url(text: str, target: str) -> str:
    return (
        "https://clients5.google.com/translate_a/t?client=dict-chrome-ex"
        f"&sl=auto&tl={urllib.parse.quote(target)}&q={urllib.parse.quote(text)}"
    )


def _single_url(host: str, client: str) -> Callable[[str, str], str]:
    def build(text: str, target: str) -> str:
        return (
            f"https://{host}/translate_a/single?client={client}"
            f"&sl=auto&tl={urllib.parse.quote(target)}"
            f"&dt=t&q={urllib.parse.quote(text)}"
        )

    return build


def parse_dict_chrome_response(payload: object) -> Translation:
    """Parse ``clients5.google.com`` / ``client=dict-chrome-ex``.

    It answers with the whole translation already joined, plus the detected
    language::

        [["Xin chào thế giới.", "en"]]
    """
    if not isinstance(payload, list) or not payload:
        raise ResponseParseError()

    first = payload[0]
    if not isinstance(first, list) or not first:
        raise ResponseParseError()

    text = first[0]
    if not isinstance(text, str) or not text:
        raise ResponseParseError()

    detected = first[1] if len(first) > 1 else None
    return Translation(
        text=text,
        detected_source=detected if isinstance(detected, str) else None,
    )


def parse_single_response(payload: object) -> Translation:
    """Parse the ``translate_a/single`` shape used by ``client=at`` and ``client=gtx``.

    It answers with a nested array rather than an object::

        [[["đã dịch", "source", ...], ["câu hai", "sentence two", ...]], null, "en", ...]

    Google splits the input into sentence-sized chunks, so the translated text
    has to be stitched back together from element ``[0]`` of every chunk.
    """
    if not isinstance(payload, list) or not payload:
        raise ResponseParseError()

    chunks = payload[0]
    if not isinstance(chunks, list):
        raise ResponseParseError()

    parts = [
        chunk[0]
        for chunk in chunks
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], str)
    ]
    text = "".join(parts)
    if not text:
        raise ResponseParseError()

    detected_source = None
    if len(payload) > 2 and isinstance(payload[2], str):
        detected_source = payload[2]

    return Translation(text=text, detected_source=detected_source)


def parse_official_response(payload: object) -> Translation:
    """Parse Cloud Translation API v2's reply."""
    if not isinstance(payload, dict):
        raise ResponseParseError()

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ResponseParseError()

    entries = data.get("translations")
    if not isinstance(entries, list) or not entries:
        raise ResponseParseError()

    first = entries[0]
    if not isinstance(first, dict):
        raise ResponseParseError()

    text = first.get("translatedText")
    if not isinstance(text, str) or not text:
        raise ResponseParseError()

    detected = first.get("detectedSourceLanguage")
    return Translation(
        text=text,
        detected_source=detected if isinstance(detected, str) else None,
    )


#: Tried in order. The first two were confirmed working; ``translate.googleapis``
#: is kept last because it is the one most commonly throttled, but it still
#: answers on plenty of networks.
FREE_PROVIDERS: tuple[FreeProvider, ...] = (
    FreeProvider("clients5/dict-chrome-ex", _dict_chrome_url, parse_dict_chrome_response),
    FreeProvider(
        "translate.google.com/at",
        _single_url("translate.google.com", "at"),
        parse_single_response,
    ),
    FreeProvider(
        "translate.googleapis.com/gtx",
        _single_url("translate.googleapis.com", "gtx"),
        parse_single_response,
    ),
)


class Translator:
    def __init__(
        self,
        target_language: str = "vi",
        alternate_language: str = "en",
        api_key: str | None = None,
        session: requests.Session | None = None,
        providers: tuple[FreeProvider, ...] = FREE_PROVIDERS,
    ) -> None:
        self.target_language = target_language
        self.alternate_language = alternate_language
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.engine = Engine.OFFICIAL if self.api_key else Engine.FREE
        self.providers = providers
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = _BROWSER_USER_AGENT

    def translate(self, text: str, target: str | None = None) -> Translation:
        """Translate ``text`` into ``target`` (default: the configured language).

        Raises a :class:`TranslateError` subclass on every failure path so the
        caller can show the reason rather than a generic error.
        """
        stripped = text.strip()
        if not stripped:
            raise EmptySelectionError()
        if len(stripped) > MAX_INPUT_CHARS:
            raise SelectionTooLongError(len(stripped))

        target = target or self.target_language
        if self.engine is Engine.OFFICIAL:
            result = self._translate_official(stripped, target)
        else:
            result = self._translate_free(stripped, target)
        return replace(result, target=target)

    def translate_auto(self, text: str) -> Translation:
        """Translate, picking the direction from what the text turns out to be.

        Selecting English gives Vietnamese; selecting Vietnamese gives English.
        The direction cannot be decided up front without a separate detection
        call, so this translates into the primary language first and only
        re-translates when the answer comes back saying the input was already in
        that language. Only the reverse direction pays for a second request.
        """
        result = self.translate(text)
        if (
            self.alternate_language
            and result.detected_source
            and result.detected_source.lower() == self.target_language.lower()
        ):
            return self.translate(text, target=self.alternate_language)
        return result

    def _translate_free(self, text: str, target: str) -> Translation:
        """Walk the provider chain, returning the first usable answer."""
        last_error: TranslateError | None = None

        for provider in self.providers:
            try:
                payload = self._request("GET", provider.build_url(text, target))
                return provider.parse(payload)
            except TranslateError as exc:
                log.debug("provider %s failed: %s", provider.name, exc)
                last_error = exc

        raise last_error or ServiceError("Không có endpoint dịch nào phản hồi.")

    def _translate_official(self, text: str, target: str) -> Translation:
        payload = self._request(
            "POST",
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": self.api_key},
            json={"q": text, "target": target, "format": "text"},
        )
        return parse_official_response(payload)

    def _request(self, method: str, url: str, **kwargs: object) -> object:
        try:
            response = self._session.request(
                method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs
            )
        except requests.Timeout as exc:
            raise ServiceError(
                f"Google Translate không phản hồi trong {REQUEST_TIMEOUT_SECONDS}s."
            ) from exc
        except requests.RequestException as exc:
            raise ServiceError(f"Không gọi được Google Translate: {exc}") from exc

        if response.status_code in (403, 429):
            raise ServiceError(
                "Google đang chặn tạm thời do gọi quá nhiều "
                f"(HTTP {response.status_code})."
            )
        if not response.ok:
            raise ServiceError(f"Google Translate trả về HTTP {response.status_code}.")

        try:
            return response.json()
        except ValueError as exc:
            raise ResponseParseError() from exc
