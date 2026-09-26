import pytest

from wintranslate.hotkey_macos import (
    CMD_KEY,
    CONTROL_KEY,
    OPTION_KEY,
    SHIFT_KEY,
    HotkeyError,
    parse_hotkey,
)


class TestParseHotkey:
    def test_parses_the_default_combination(self):
        assert parse_hotkey("ctrl+alt+t") == (CONTROL_KEY | OPTION_KEY, 0x11)

    def test_is_case_and_space_insensitive(self):
        assert parse_hotkey(" Ctrl + Shift + K ") == parse_hotkey("ctrl+shift+k")

    def test_mac_names_match_the_windows_names(self):
        assert parse_hotkey("control+option+t") == parse_hotkey("ctrl+alt+t")
        assert parse_hotkey("command+t") == parse_hotkey("win+t")

    def test_accepts_every_modifier(self):
        modifiers, _ = parse_hotkey("ctrl+cmd+shift+opt+q")
        assert modifiers == CONTROL_KEY | CMD_KEY | SHIFT_KEY | OPTION_KEY

    def test_uses_physical_key_codes_not_ascii(self):
        # kVK_ANSI_A is 0 and kVK_ANSI_1 is 0x12: nothing like ord().
        assert parse_hotkey("ctrl+a")[1] == 0x00
        assert parse_hotkey("ctrl+1")[1] == 0x12
        assert parse_hotkey("ctrl+0")[1] == 0x1D

    def test_every_letter_and_digit_has_a_distinct_code(self):
        keys = "abcdefghijklmnopqrstuvwxyz0123456789"
        codes = {parse_hotkey(f"ctrl+{key}")[1] for key in keys}
        assert len(codes) == len(keys)

    def test_parses_function_keys(self):
        assert parse_hotkey("ctrl+f1")[1] == 0x7A
        assert parse_hotkey("ctrl+f12")[1] == 0x6F
        assert parse_hotkey("ctrl+f20")[1] == 0x5A

    def test_parses_named_keys(self):
        assert parse_hotkey("ctrl+alt+space")[1] == 0x31
        assert parse_hotkey("ctrl+alt+pagedown")[1] == 0x79

    def test_rejects_a_bare_key_with_no_modifier(self):
        with pytest.raises(HotkeyError, match="at least one modifier"):
            parse_hotkey("t")

    def test_rejects_an_unknown_modifier(self):
        with pytest.raises(HotkeyError, match="Unknown modifier"):
            parse_hotkey("hyper+t")

    def test_rejects_an_unknown_key(self):
        with pytest.raises(HotkeyError, match="Unknown key"):
            parse_hotkey("ctrl+alt+nonsense")

    def test_rejects_a_function_key_macos_does_not_have(self):
        with pytest.raises(HotkeyError):
            parse_hotkey("ctrl+f21")

    def test_rejects_an_empty_spec(self):
        with pytest.raises(HotkeyError, match="Empty hotkey"):
            parse_hotkey("   ")
