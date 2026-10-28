"""The settings window and the data behind its rows."""

import pytest
from PySide6.QtCore import Qt

from wintranslate import languages, theme


class TestLanguages:
    def test_every_code_is_unique(self):
        codes = [language.code for language in languages.LANGUAGES]
        assert len(codes) == len(set(codes))

    def test_the_default_target_and_alternate_are_both_offered(self):
        assert languages.get("vi") is not None
        assert languages.get("en") is not None

    def test_lookup_is_case_insensitive(self):
        assert languages.get("VI").code == "vi"
        assert languages.get("zh-cn").code == "zh-CN"

    def test_a_regional_code_falls_back_to_its_base(self):
        """Google answers pt-BR where the list carries pt."""
        assert languages.get("pt-BR").code == "pt"

    def test_an_unknown_code_is_none_rather_than_a_guess(self):
        assert languages.get("klingon") is None
        assert languages.get("") is None

    def test_label_falls_back_to_the_raw_code(self):
        assert languages.label("klingon") == "KLINGON"

    def test_label_does_not_repeat_a_name_that_matches_its_endonym(self):
        assert languages.label("en") == "English"
        assert "—" in languages.label("vi")

    def test_every_language_carries_a_flag(self):
        """A blank flag is reserved for a code the list does not know at all."""
        for language in languages.LANGUAGES:
            assert language.region, language.code

    def test_a_language_spoken_across_states_takes_its_largest(self):
        """The rule is speakers, not where the language is named after."""
        assert languages.get("ar").region == "EG"
        assert languages.get("sw").region == "TZ"
        assert languages.get("ha").region == "NG"

    def test_a_country_derived_code_keeps_its_own_country(self):
        """es has more speakers in Mexico, but the code means Spain."""
        assert languages.get("es").region == "ES"
        assert languages.get("pt").region == "PT"
        assert languages.get("en").region == "GB"

    def test_esperanto_carries_its_own_flag_not_a_country(self):
        assert languages.get("eo").region == "EO"

    def test_regions_are_two_letter_codes(self):
        for language in languages.LANGUAGES:
            assert len(language.region.split("-")[0]) == 2, language.code

    def test_every_region_has_an_asset_on_disk(self):
        """A region with no file renders blank, which is what this guards."""
        from wintranslate import flags

        for language in languages.LANGUAGES:
            path = flags.FLAG_DIR / f"{language.region.lower()}.svg"
            assert path.is_file(), f"{language.code} wants {path.name}"


class TestThemes:
    def test_every_theme_is_offered_in_order(self):
        assert [option.key for option in theme.THEMES] == [
            "light", "dark", "colorful", "neon",
        ]

    def test_an_unknown_key_falls_back_instead_of_raising(self):
        assert theme.get("chartreuse") is theme.DEFAULT
        assert theme.get("") is theme.DEFAULT

    def test_lookup_ignores_case_and_padding(self):
        assert theme.get("  Light ") is theme.LIGHT

    def test_the_stylesheet_carries_the_theme_colours(self):
        sheet = theme.popup_stylesheet(theme.LIGHT)
        assert theme.LIGHT.card in sheet
        assert theme.DARK.card not in sheet

    def test_both_windows_get_a_stylesheet_for_every_theme(self):
        for option in theme.THEMES:
            assert theme.popup_stylesheet(option)
            assert theme.settings_stylesheet(option)

    def test_the_scroll_viewport_is_made_transparent_in_every_theme(self):
        """The rule that keeps the translation off a white block.

        Checked by what it targets, not by its exact text: the selector was
        narrowed once already, and a test that pins the wording would have to
        change again for a fix that is none of its business.
        """
        for option in theme.THEMES:
            sheet = theme.popup_stylesheet(option)
            assert "qt_scrollarea_viewport" in sheet, option.key
            rule = sheet.split("qt_scrollarea_viewport")[1].split("}")[0]
            assert "background: transparent" in rule, option.key

    def test_the_viewport_rule_does_not_reach_the_label_inside_it(self):
        """`QScrollArea > QWidget > QWidget` also matched the translation, and
        a background rule on a widget collapses a gradient colour to its last
        stop -- measured, the four-stop text went flat #12715a."""
        for option in theme.THEMES:
            assert (
                "QScrollArea > QWidget > QWidget" not in theme.popup_stylesheet(option)
            ), option.key

    def test_the_stylesheet_url_survives_a_path_with_spaces(self):
        """Unquoted, the rule is dropped at the first space and the control
        loses its arrows. A checkout under ~/My Projects is enough to hit it."""
        sheet = theme.popup_stylesheet(theme.LIGHT)
        for line in sheet.splitlines():
            if "url(" in line:
                inside = line.split("url(", 1)[1].split(")", 1)[0]
                assert inside.startswith('"') and inside.endswith('"'), line.strip()

    def test_the_stylesheet_points_at_files_that_exist(self):
        """A url to nowhere is silently ignored, leaving no arrows at all."""
        from pathlib import Path as _Path

        for option in theme.THEMES:
            for line in theme.popup_stylesheet(option).splitlines():
                if "url(" in line:
                    inside = line.split("url(", 1)[1].split(")", 1)[0].strip('"')
                    assert _Path(inside).is_file(), inside

    def test_the_soft_chevron_assets_exist_for_every_theme(self):
        """A missing asset leaves the spin box with no arrows at all."""
        for option in theme.THEMES:
            for direction in ("up", "down"):
                assert (
                    theme.ASSETS / f"chevron-{direction}-{option.chevron}.svg"
                ).is_file()

    def test_the_primary_label_reads_on_every_stop_of_its_button(self):
        """A gradient button is only as readable as its worst stop, so the
        label is measured against each one rather than against an average."""
        from PySide6.QtGui import QColor

        for option in theme.THEMES:
            fill = option.primary_stops or ((0.0, option.accent),)
            label = QColor(option.primary_fg).lightness()
            for _, colour in fill:
                gap = abs(QColor(colour).lightness() - label)
                assert gap > 70, f"{option.key}: {option.primary_fg} on {colour} ({gap})"

    def test_every_text_stop_reads_on_every_card_stop(self):
        """Gradient text over a gradient card has a trap of its own: a colour
        that reads at one end of the pane can vanish at the other. Checked
        against the declared stops, not sampled pixels."""
        from PySide6.QtGui import QColor

        for option in theme.THEMES:
            text = option.text_stops or ((0.0, option.title),)
            worst = min(
                (
                    abs(QColor(t).lightness() - QColor(c).lightness()), t, c)
                for _, t in text
                for _, c in option.card_stops
            )
            gap, text_colour, card_colour = worst
            assert gap > 60, (
                f"{option.key}: {text_colour} on {card_colour} differs by only {gap}"
            )

    def test_a_gradient_theme_renders_its_translation_as_a_gradient(self):
        for option in (theme.COLORFUL, theme.NEON):
            assert "qlineargradient" in option.translation_colour, option.key
        for option in (theme.LIGHT, theme.DARK):
            assert option.translation_colour == option.title, option.key

    def test_the_error_and_waiting_states_stay_one_colour(self):
        """They must not inherit the gradient, or they stop reading as
        anything other than a translation."""
        for option in theme.THEMES:
            sheet = theme.popup_stylesheet(option)
            error = sheet.split('#translation[state="error"]')[1].split("}")[0]
            assert "qlineargradient" not in error, option.key


class TestHotkeyCapture:
    @pytest.fixture(autouse=True)
    def _qt(self, qapp):
        return qapp

    def test_a_plain_combination_is_recorded(self):
        from PySide6.QtCore import Qt

        from wintranslate.settings import qt_to_spec

        spec = qt_to_spec(Qt.Key_T, Qt.ControlModifier | Qt.AltModifier)
        assert spec == "ctrl+alt+t"

    def test_a_bare_modifier_is_not_a_combination_yet(self):
        from PySide6.QtCore import Qt

        from wintranslate.settings import qt_to_spec

        for key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            assert qt_to_spec(key, Qt.ControlModifier) is None

    def test_a_key_with_no_modifier_is_refused(self):
        """It would swallow that key for every application."""
        from PySide6.QtCore import Qt

        from wintranslate.settings import qt_to_spec

        assert qt_to_spec(Qt.Key_T, Qt.NoModifier) is None

    def test_function_and_named_keys_are_recorded(self):
        from PySide6.QtCore import Qt

        from wintranslate.settings import qt_to_spec

        assert qt_to_spec(Qt.Key_F5, Qt.ControlModifier) == "ctrl+f5"
        assert qt_to_spec(Qt.Key_Space, Qt.ControlModifier | Qt.ShiftModifier) == (
            "ctrl+shift+space"
        )

    def test_whatever_it_records_the_parser_accepts(self):
        """The two halves have to agree or the capture produces dead settings."""
        import sys

        if sys.platform != "win32":
            pytest.skip("the parser binds user32")
        from PySide6.QtCore import Qt

        from wintranslate.hotkey import parse_hotkey
        from wintranslate.settings import qt_to_spec

        for key, mods in [
            (Qt.Key_T, Qt.ControlModifier | Qt.AltModifier),
            (Qt.Key_F9, Qt.ControlModifier),
            (Qt.Key_Space, Qt.MetaModifier | Qt.ShiftModifier),
            (Qt.Key_1, Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier),
        ]:
            parse_hotkey(qt_to_spec(key, mods))  # raises on anything invalid

    def test_pretty_reads_as_a_combination(self):
        from wintranslate.settings import pretty

        assert pretty("ctrl+alt+t") == "Ctrl + Alt + T"


class TestFlags:
    def test_a_language_with_no_assets_still_gets_an_icon(self, qapp):
        """An unknown region falls back rather than leaving an empty row."""
        from wintranslate import flags

        assert not flags.icon("VN").isNull()
        assert not flags.icon(None).isNull()
        assert not flags.icon("ZZ").isNull()

    def test_a_real_flag_is_not_the_blank_placeholder(self, qapp):
        """Both are non-null icons, so only the pixels tell them apart."""
        from wintranslate import flags

        def colours(region):
            image = flags.icon(region).pixmap(flags.SIZE).toImage()
            return {
                image.pixelColor(x, y).name()
                for x in range(2, flags.SIZE.width() - 2, 3)
                for y in range(2, flags.SIZE.height() - 2, 3)
            }

        assert len(colours("VN")) > len(colours("ZZ"))

    def test_the_blank_flag_and_a_missing_one_are_the_same_size(self, qapp):
        from wintranslate import flags

        assert flags.icon(None).pixmap(flags.SIZE).size() == flags.SIZE


class TestSettingsDialog:
    @pytest.fixture
    def dialog(self, qapp):
        from wintranslate.config import Config
        from wintranslate.settings import SettingsDialog

        applied = []
        widget = SettingsDialog(Config(), lambda config: applied.append(config) or None)
        widget._applied = applied
        return widget

    def test_every_language_is_offered(self, dialog):
        assert dialog._language.count() == len(languages.LANGUAGES)

    def test_it_opens_on_the_configured_language(self, dialog):
        assert dialog._language.currentData() == "vi"

    def test_a_change_is_applied_immediately(self, dialog):
        dialog._language.setCurrentIndex(dialog._language.findData("ja"))
        assert dialog._applied[-1].target_language == "ja"
        assert dialog.config().target_language == "ja"

    def test_a_refused_change_reverts_and_is_explained(self, qapp):
        from wintranslate.config import Config
        from wintranslate.settings import SettingsDialog

        # Stated rather than left to Config(): the default differs per platform
        # (ctrl+t on macOS), and this test is about the old value surviving.
        widget = SettingsDialog(
            Config(hotkey="ctrl+alt+t"), lambda config: "that hotkey is taken"
        )
        widget._on_hotkey("ctrl+alt+j")
        assert widget.config().hotkey == "ctrl+alt+t", "the old setting must survive"
        assert "taken" in widget._status.text()

    def test_a_code_outside_the_list_is_kept_not_silently_replaced(self, qapp):
        from wintranslate.config import Config
        from wintranslate.settings import SettingsDialog

        widget = SettingsDialog(Config(target_language="klingon"), lambda c: None)
        assert widget._language.currentData() == "klingon"

    def test_the_switch_reports_both_states(self, dialog):
        dialog._detected.mousePressEvent(None)
        assert dialog._applied[-1].show_detected_language is False
        dialog._detected.mousePressEvent(None)
        assert dialog._applied[-1].show_detected_language is True

    def test_popup_size_and_theme_travel_together(self, dialog):
        dialog._theme.setCurrentIndex(dialog._theme.findData("colorful"))
        assert dialog._applied[-1].theme == "colorful"
        assert dialog._applied[-1].popup_width == dialog._width.value()

    def test_the_window_stays_light_whatever_the_theme_setting_is(self, qapp):
        """The theme is about the popup. This window is opened deliberately and
        gains nothing from following it."""
        from wintranslate.config import Config
        from wintranslate.settings import SettingsDialog

        for key in ("light", "dark", "colorful"):
            widget = SettingsDialog(Config(theme=key), lambda c: None)
            assert theme.LIGHT.card in widget.styleSheet(), key
            assert theme.DARK.card not in widget.styleSheet(), key

    def test_the_card_is_flush_inside_the_native_frame(self, qapp):
        """Rounded corners inside a square frame only show the gap behind."""
        from wintranslate.config import Config
        from wintranslate.settings import SettingsDialog

        widget = SettingsDialog(Config(), lambda c: None)
        assert "#card { border-radius: 0; border: none; }" in widget.styleSheet()

    def test_theme_and_the_switch_sit_on_the_same_row(self, dialog, qapp):
        """They were two rows and are now one, split in half."""
        dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        dialog.show()
        qapp.processEvents()

        theme_box = dialog._theme.mapTo(dialog, dialog._theme.rect().center())
        switch = dialog._detected.mapTo(dialog, dialog._detected.rect().center())
        assert abs(theme_box.y() - switch.y()) < 12, "they must share a row"
        # Two columns side by side: the switch starts after the theme control
        # ends. Its centre does not cross the midpoint because each control is
        # left-aligned under its own label.
        theme_right = dialog._theme.mapTo(dialog, dialog._theme.rect().topRight()).x()
        switch_left = dialog._detected.mapTo(dialog, dialog._detected.rect().topLeft()).x()
        assert switch_left > theme_right, (
            f"columns overlap: theme ends at {theme_right}, switch starts at {switch_left}"
        )


class TestPortability:
    """The interface has to build on macOS as well as Windows."""

    def test_the_ui_pulls_in_no_platform_module(self):
        """settings/popup/theme/flags must not reach the Win32 or Cocoa layer:
        importing one on the wrong platform fails at module load.

        Checked in a fresh interpreter, because by the time this runs the rest
        of the suite has already imported those modules into sys.modules -- the
        in-process version of this test passes or fails on test order.
        """
        import json
        import subprocess
        import sys
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parent.parent
        code = "\n".join(
            [
                "import sys, importlib, json",
                "for name in ['wintranslate.theme', 'wintranslate.flags',",
                "             'wintranslate.languages', 'wintranslate.settings',",
                "             'wintranslate.popup', 'wintranslate.config']:",
                "    importlib.import_module(name)",
                "leaked = [n for n in sys.modules if n.startswith('wintranslate.')",
                "          and any(p in n for p in ['hotkey', 'selection', 'macos'])]",
                "print(json.dumps(leaked))",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=root,
            env={**__import__("os").environ, "PYTHONPATH": str(root)},
        )
        assert result.returncode == 0, result.stderr
        leaked = json.loads(result.stdout.strip().splitlines()[-1])
        assert not leaked, leaked

    def test_no_font_is_hardcoded_in_the_interface(self):
        """A named font is a per-platform choice; the UI takes the system one."""
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parent.parent / "wintranslate"
        for name in ("settings.py", "popup.py", "theme.py", "flags.py"):
            source = (root / name).read_text(encoding="utf-8")
            assert "QFont(" not in source, name
            assert "font-family" not in source, name

    def test_asset_paths_are_derived_from_the_package_location(self):
        """Not an absolute path baked in at authoring time, which would be a
        Windows path on a Mac."""
        from pathlib import Path as _Path

        from wintranslate import flags

        root = _Path(flags.__file__).resolve().parent.parent
        assert flags.FLAG_DIR == root / "assets" / "flags"
        assert theme.ASSETS == root / "assets" / "ui"
