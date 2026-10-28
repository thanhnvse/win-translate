"""The languages the app can translate into, with the region used for a flag.

The codes are the ones Google Translate accepts. ``region`` is an ISO 3166-1
alpha-2 code naming the flag to show.

Where a language is spoken in several countries, the region is the one with the
most speakers: Arabic shows Egypt, Swahili Tanzania, Hausa Nigeria. Where the
language code is itself derived from a country, that country wins over raw
speaker counts, because it is what the code means and what people expect --
``es`` shows Spain though Mexico has more speakers, ``pt`` shows Portugal, and
``en`` shows the United Kingdom.

Esperanto carries ``EO``, which is not a country code: it belongs to no
country and has a flag of its own. The field is the name of a flag asset, not a
claim about statehood, so there is nothing to work around here.

``region`` is never ``None`` -- a blank flag is reserved for a code the list
does not know at all.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    #: English name, for searching and for people whose own script the list
    #: cannot render.
    name: str
    #: The name in the language itself, which is what its speakers look for.
    endonym: str
    #: ISO 3166-1 alpha-2 for the flag, or None for a blank one.
    region: str | None


#: Ordered by English name so the list reads predictably; the UI sorts its own
#: way and pins recently used entries to the top.
LANGUAGES: tuple[Language, ...] = (
    Language("af", "Afrikaans", "Afrikaans", "ZA"),
    Language("sq", "Albanian", "Shqip", "AL"),
    Language("am", "Amharic", "አማርኛ", "ET"),
    Language("ar", "Arabic", "العربية", "EG"),
    Language("hy", "Armenian", "Հայերեն", "AM"),
    Language("az", "Azerbaijani", "Azərbaycan", "AZ"),
    Language("eu", "Basque", "Euskara", "ES"),
    Language("be", "Belarusian", "Беларуская", "BY"),
    Language("bn", "Bengali", "বাংলা", "BD"),
    Language("bs", "Bosnian", "Bosanski", "BA"),
    Language("bg", "Bulgarian", "Български", "BG"),
    Language("ca", "Catalan", "Català", "ES"),
    Language("ceb", "Cebuano", "Cebuano", "PH"),
    Language("zh-CN", "Chinese (Simplified)", "简体中文", "CN"),
    Language("zh-TW", "Chinese (Traditional)", "繁體中文", "TW"),
    Language("co", "Corsican", "Corsu", "FR"),
    Language("hr", "Croatian", "Hrvatski", "HR"),
    Language("cs", "Czech", "Čeština", "CZ"),
    Language("da", "Danish", "Dansk", "DK"),
    Language("nl", "Dutch", "Nederlands", "NL"),
    Language("en", "English", "English", "GB"),
    Language("eo", "Esperanto", "Esperanto", "EO"),
    Language("et", "Estonian", "Eesti", "EE"),
    Language("fi", "Finnish", "Suomi", "FI"),
    Language("fr", "French", "Français", "FR"),
    Language("fy", "Frisian", "Frysk", "NL"),
    Language("gl", "Galician", "Galego", "ES"),
    Language("ka", "Georgian", "ქართული", "GE"),
    Language("de", "German", "Deutsch", "DE"),
    Language("el", "Greek", "Ελληνικά", "GR"),
    Language("gu", "Gujarati", "ગુજરાતી", "IN"),
    Language("ht", "Haitian Creole", "Kreyòl ayisyen", "HT"),
    Language("ha", "Hausa", "Hausa", "NG"),
    Language("haw", "Hawaiian", "ʻŌlelo Hawaiʻi", "US"),
    Language("he", "Hebrew", "עברית", "IL"),
    Language("hi", "Hindi", "हिन्दी", "IN"),
    Language("hmn", "Hmong", "Hmoob", "CN"),
    Language("hu", "Hungarian", "Magyar", "HU"),
    Language("is", "Icelandic", "Íslenska", "IS"),
    Language("ig", "Igbo", "Igbo", "NG"),
    Language("id", "Indonesian", "Bahasa Indonesia", "ID"),
    Language("ga", "Irish", "Gaeilge", "IE"),
    Language("it", "Italian", "Italiano", "IT"),
    Language("ja", "Japanese", "日本語", "JP"),
    Language("jv", "Javanese", "Basa Jawa", "ID"),
    Language("kn", "Kannada", "ಕನ್ನಡ", "IN"),
    Language("kk", "Kazakh", "Қазақ", "KZ"),
    Language("km", "Khmer", "ខ្មែរ", "KH"),
    Language("rw", "Kinyarwanda", "Kinyarwanda", "RW"),
    Language("ko", "Korean", "한국어", "KR"),
    Language("ku", "Kurdish", "Kurdî", "TR"),
    Language("ky", "Kyrgyz", "Кыргызча", "KG"),
    Language("lo", "Lao", "ລາວ", "LA"),
    Language("la", "Latin", "Latina", "VA"),
    Language("lv", "Latvian", "Latviešu", "LV"),
    Language("lt", "Lithuanian", "Lietuvių", "LT"),
    Language("lb", "Luxembourgish", "Lëtzebuergesch", "LU"),
    Language("mk", "Macedonian", "Македонски", "MK"),
    Language("mg", "Malagasy", "Malagasy", "MG"),
    Language("ms", "Malay", "Bahasa Melayu", "MY"),
    Language("ml", "Malayalam", "മലയാളം", "IN"),
    Language("mt", "Maltese", "Malti", "MT"),
    Language("mi", "Maori", "Te Reo Māori", "NZ"),
    Language("mr", "Marathi", "मराठी", "IN"),
    Language("mn", "Mongolian", "Монгол", "MN"),
    Language("my", "Myanmar (Burmese)", "မြန်မာ", "MM"),
    Language("ne", "Nepali", "नेपाली", "NP"),
    Language("no", "Norwegian", "Norsk", "NO"),
    Language("ny", "Nyanja (Chichewa)", "Chichewa", "MW"),
    Language("or", "Odia (Oriya)", "ଓଡ଼ିଆ", "IN"),
    Language("ps", "Pashto", "پښتو", "AF"),
    Language("fa", "Persian", "فارسی", "IR"),
    Language("pl", "Polish", "Polski", "PL"),
    Language("pt", "Portuguese", "Português", "PT"),
    Language("pa", "Punjabi", "ਪੰਜਾਬੀ", "IN"),
    Language("ro", "Romanian", "Română", "RO"),
    Language("ru", "Russian", "Русский", "RU"),
    Language("sm", "Samoan", "Gagana Samoa", "WS"),
    Language("gd", "Scots Gaelic", "Gàidhlig", "GB-SCT"),
    Language("sr", "Serbian", "Српски", "RS"),
    Language("st", "Sesotho", "Sesotho", "LS"),
    Language("sn", "Shona", "ChiShona", "ZW"),
    Language("sd", "Sindhi", "سنڌي", "PK"),
    Language("si", "Sinhala", "සිංහල", "LK"),
    Language("sk", "Slovak", "Slovenčina", "SK"),
    Language("sl", "Slovenian", "Slovenščina", "SI"),
    Language("so", "Somali", "Soomaali", "SO"),
    Language("es", "Spanish", "Español", "ES"),
    Language("su", "Sundanese", "Basa Sunda", "ID"),
    Language("sw", "Swahili", "Kiswahili", "TZ"),
    Language("sv", "Swedish", "Svenska", "SE"),
    Language("tl", "Tagalog (Filipino)", "Tagalog", "PH"),
    Language("tg", "Tajik", "Тоҷикӣ", "TJ"),
    Language("ta", "Tamil", "தமிழ்", "IN"),
    Language("tt", "Tatar", "Татарча", "RU"),
    Language("te", "Telugu", "తెలుగు", "IN"),
    Language("th", "Thai", "ไทย", "TH"),
    Language("tr", "Turkish", "Türkçe", "TR"),
    Language("tk", "Turkmen", "Türkmen", "TM"),
    Language("uk", "Ukrainian", "Українська", "UA"),
    Language("ur", "Urdu", "اردو", "PK"),
    Language("ug", "Uyghur", "ئۇيغۇرچە", "CN"),
    Language("uz", "Uzbek", "Oʻzbek", "UZ"),
    Language("vi", "Vietnamese", "Tiếng Việt", "VN"),
    Language("cy", "Welsh", "Cymraeg", "GB-WLS"),
    Language("xh", "Xhosa", "isiXhosa", "ZA"),
    Language("yi", "Yiddish", "ייִדיש", "IL"),
    Language("yo", "Yoruba", "Yorùbá", "NG"),
    Language("zu", "Zulu", "isiZulu", "ZA"),
)

BY_CODE: dict[str, Language] = {language.code: language for language in LANGUAGES}


def get(code: str) -> Language | None:
    """Return the language for ``code``, matching the way Google reports it.

    Google answers ``zh-CN`` where a config may say ``zh``, and casing differs
    between endpoints, so the lookup is case-insensitive and falls back to the
    part before the hyphen.
    """
    if not code:
        return None
    normalised = code.strip()
    for candidate in (normalised, normalised.lower()):
        for language in LANGUAGES:
            if language.code.lower() == candidate.lower():
                return language
    base = normalised.split("-")[0].lower()
    for language in LANGUAGES:
        if language.code.lower() == base:
            return language
    return None


def label(code: str) -> str:
    """How a language is written in the UI, for a code that may be unknown."""
    language = get(code)
    if language is None:
        return code.upper()
    if language.endonym == language.name:
        return language.name
    return f"{language.name} — {language.endonym}"
