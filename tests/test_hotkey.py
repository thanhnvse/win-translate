import pytest

from wintranslate.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    HotkeyError,
    parse_hotkey,
)


class TestParseHotkey:
    def test_parses_the_default_combination(self):
        modifiers, virtual_key = parse_hotkey("ctrl+alt+t")
        assert modifiers == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        assert virtual_key == ord("T")

    def test_is_case_and_space_insensitive(self):
        assert parse_hotkey(" Ctrl + Shift + K ") == parse_hotkey("ctrl+shift+k")

    def test_accepts_every_modifier_alias(self):
        modifiers, _ = parse_hotkey("control+super+shift+alt+q")
        assert modifiers == MOD_CONTROL | MOD_WIN | MOD_SHIFT | MOD_ALT | MOD_NOREPEAT

    def test_always_sets_norepeat(self):
        modifiers, _ = parse_hotkey("ctrl+alt+t")
        assert modifiers & MOD_NOREPEAT

    def test_parses_digits(self):
        _, virtual_key = parse_hotkey("ctrl+alt+1")
        assert virtual_key == ord("1")

    def test_parses_function_keys(self):
        assert parse_hotkey("ctrl+f1")[1] == 0x70
        assert parse_hotkey("ctrl+f12")[1] == 0x7B

    def test_parses_named_keys(self):
        assert parse_hotkey("ctrl+alt+space")[1] == 0x20
        assert parse_hotkey("ctrl+alt+pagedown")[1] == 0x22

    def test_rejects_a_bare_key_with_no_modifier(self):
        with pytest.raises(HotkeyError, match="at least one modifier"):
            parse_hotkey("t")

    def test_rejects_an_unknown_modifier(self):
        with pytest.raises(HotkeyError, match="Unknown modifier"):
            parse_hotkey("hyper+t")

    def test_rejects_an_unknown_key(self):
        with pytest.raises(HotkeyError, match="Unknown key"):
            parse_hotkey("ctrl+alt+nonsense")

    def test_rejects_an_out_of_range_function_key(self):
        with pytest.raises(HotkeyError):
            parse_hotkey("ctrl+f25")

    def test_rejects_an_empty_spec(self):
        with pytest.raises(HotkeyError, match="Empty hotkey"):
            parse_hotkey("   ")
