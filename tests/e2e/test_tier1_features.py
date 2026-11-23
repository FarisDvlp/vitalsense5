"""Tier 1 Opaque-Box E2E Tests: Happy-path feature coverage across F1-F10 (56 tests).

Zero top-level imports of ``vitalsense5`` or ``PyQt6``.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from tests.e2e import conftest as h


def _assert_vital_value_rendered(
    col_widget: object,
    expected_tokens: tuple[str, ...],
    before_img: object | None = None,
) -> None:
    """Verify vital column reflects expected value via visible QLabel text or QPainter pixel diff."""
    txt = h.joined_text(col_widget)
    if any(tok in txt for tok in expected_tokens):
        return
    if before_img is not None:
        after_img = h.grab_image(col_widget)
        assert h.images_differ(before_img, after_img), (
            f"Neither expected tokens {expected_tokens} in text {txt!r} nor pixel change detected"
        )
        return
    pytest.fail(f"Expected one of {expected_tokens} in vital column text, got {txt!r}")


# ===========================================================================
# F1: Frontend Plan & Gap Report Deliverables (6 tests)
# ===========================================================================


def test_f1_deliverable_docs_and_readme_exist() -> None:
    readme = h.REPO_ROOT / "README.md"
    plan = h.REPO_ROOT / "docs" / "FRONTEND_PLAN.md"
    gap = h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md"
    for path in (readme, plan, gap):
        assert path.is_file(), f"Missing required deliverable: {path}"
        assert path.stat().st_size > 500, f"Deliverable {path} is unexpectedly small"


def test_f1_frontend_plan_covers_screens_and_ports() -> None:
    plan_text = (h.REPO_ROOT / "docs" / "FRONTEND_PLAN.md").read_text(encoding="utf-8")
    for alternatives in (
        ("Main Screen", "MainScreen"),
        ("Patient Screen", "PatientScreen"),
        ("Settings", "SettingsModal"),
        ("New Patient", "NewPatientDialog"),
        ("1280x720",),
        ("VitalDataPort",),
        ("PatientStorePort",),
        ("SettingsPort",),
        ("SessionCommandPort",),
    ):
        assert any(tok in plan_text for tok in alternatives), (
            f"FRONTEND_PLAN.md missing expected section/contract {alternatives!r}"
        )


def test_f1_gap_report_covers_undefined_settings_and_buttons() -> None:
    gap_text = (h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md").read_text(encoding="utf-8")
    for token in ("SETTINGS 1", "SETTINGS 8", "SAVE", "RECORD", "EDIT PATIENT"):
        assert token in gap_text, f"DESIGN_GAP_REPORT.md missing button/settings gap {token!r}"
    assert "delete" in gap_text.lower() or "deletion" in gap_text.lower()
    assert "validat" in gap_text.lower()


def test_f1_gap_report_covers_hardware_sensor_alarm_and_bpm() -> None:
    gap_text = (h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md").read_text(encoding="utf-8")
    lower = gap_text.lower()
    for term in ("uart", "finger", "battery", "cloud", "alarm", "bpm"):
        assert term in lower, f"DESIGN_GAP_REPORT.md missing hardware/alarm gap {term!r}"


def test_f1_bundled_fonts_and_vs5_svg_assets_valid(qapp: object) -> None:
    from PyQt6.QtSvg import QSvgRenderer

    fonts_dir = h.REPO_ROOT / "assets" / "fonts"
    icons_dir = h.REPO_ROOT / "assets" / "icons"
    ttf_files = list(fonts_dir.glob("*.ttf"))
    assert ttf_files, f"No .ttf font files found in {fonts_dir}"
    assert any("jetbrains" in f.name.lower() for f in ttf_files), "No JetBrainsMono font file found"

    svg_files = list(icons_dir.glob("*.svg"))
    assert svg_files, f"No .svg icon files found in {icons_dir}"
    logo_svgs = [s for s in svg_files if "logo" in s.name.lower() or "vs5" in s.name.lower()]
    target_svg = logo_svgs[0] if logo_svgs else svg_files[0]
    ET.parse(target_svg)
    renderer = QSvgRenderer(str(target_svg))
    assert renderer.isValid(), f"QSvgRenderer rejected SVG asset {target_svg}"


def test_f1_package_metadata_declares_pyqt6_and_entrypoint() -> None:
    pyproject = (h.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (h.REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "PyQt6" in pyproject
    assert "vitalsense5" in pyproject
    assert "PyQt6" in requirements


# ===========================================================================
# F2: Main Screen Vitals & Live PPG Display (7 tests)
# ===========================================================================


def test_f2_main_screen_renders_all_five_vital_columns(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    expected = {
        "vital_prv": (("68",), ("PRV", "RMSSD", "ms")),
        "vital_rr": (("16",), ("RR", "brpm")),
        "vital_pi": (("03", "3", "3.0"), ("PI", "%")),
        "vital_spo2": (("98",), ("SpO2", "%")),
        "vital_bp": (("120", "80"), ("BP", "SYS", "DIA", "mmHg")),
    }
    for obj_name, (val_tokens, label_tokens) in expected.items():
        col = h.find_widget(screen, obj_name)
        assert col.isVisible(), f"{obj_name} is not visible"
        txt = h.joined_text(col)
        if txt:
            for lbl in label_tokens:
                assert lbl in txt, f"{obj_name} missing label/unit {lbl!r} in {txt!r}"
            assert any(tok in txt for tok in val_tokens), f"{obj_name} missing value {val_tokens} in {txt!r}"
        else:
            assert col.width() > 60 and col.height() > 100


def test_f2_vital_columns_live_update_from_vital_port(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    cols = {name: h.find_widget(screen, name) for name in ("vital_prv", "vital_rr", "vital_pi", "vital_spo2", "vital_bp")}
    before_imgs = {name: h.grab_image(col) for name, col in cols.items()}

    harness.vital_port.push_vitals(
        prv_rmssd_ms=74.0,
        rr_brpm=18.0,
        pi_percent=4.2,
        spo2_percent=99.0,
        bp_sys_mmhg=118,
        bp_dia_mmhg=76,
    )
    h.pump_events(120)

    _assert_vital_value_rendered(cols["vital_prv"], ("74",), before_imgs["vital_prv"])
    _assert_vital_value_rendered(cols["vital_rr"], ("18",), before_imgs["vital_rr"])
    _assert_vital_value_rendered(cols["vital_pi"], ("4.2", "04", "4"), before_imgs["vital_pi"])
    _assert_vital_value_rendered(cols["vital_spo2"], ("99",), before_imgs["vital_spo2"])
    _assert_vital_value_rendered(cols["vital_bp"], ("118", "76"), before_imgs["vital_bp"])


def test_f2_vital_accent_bars_and_canvas_colors_match_figma(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    assert h.region_has_color(screen, "#EDEDED", min_pixels=500), "Main screen canvas #EDEDED missing"

    accent_map = {
        "vital_prv": "#CD5656",
        "vital_rr": "#E98D62",
        "vital_pi": "#B369D3",
        "vital_spo2": "#64C25E",
        "vital_bp": "#4E54A7",
    }
    for obj_name, hex_color in accent_map.items():
        col = h.find_widget(screen, obj_name)
        assert h.region_has_color(col, hex_color, tolerance=22, stride=1, min_pixels=10), (
            f"{obj_name} missing Figma accent bar color {hex_color}"
        )


def test_f2_ppg_canvas_geometry_colors_and_live_trace(harness: h.AppHarness) -> None:
    ppg = h.find_widget(harness.window, "ppg_canvas")
    assert ppg.isVisible()
    assert abs(ppg.width() - 1124) <= 16
    assert abs(ppg.height() - 250) <= 16

    harness.vital_port.push_waveform([0.0, 0.8, 0.3, 0.5, -0.4, -0.7, 0.0, 0.9] * 6)
    h.pump_events(120)

    img = h.grab_image(ppg)
    assert h.count_color_pixels(img, "#E4E4E4", tolerance=18, stride=2) >= 200
    assert h.count_color_pixels(img, "#D2D2D2", tolerance=18, stride=2) >= 20
    assert h.count_color_pixels(img, "#C9C9C9", tolerance=18, stride=2) >= 20
    assert h.count_color_pixels(img, "#313131", tolerance=24, stride=1) >= 15


def test_f2_header_shows_active_patient_datetime_uart_battery(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    lbl_patient = h.find_widget(screen, "lbl_active_patient")
    lbl_dt = h.find_widget(screen, "lbl_datetime")
    lbl_uart = h.find_widget(screen, "lbl_uart_status")
    lbl_bat = h.find_widget(screen, "lbl_battery_pct")

    assert "Patient Number 1" in lbl_patient.text()
    assert lbl_dt.text().strip() != ""
    uart_txt = lbl_uart.text().upper()
    assert "CONNECTED" in uart_txt or "UART" in uart_txt or "ESP32" in uart_txt
    assert "95%" in lbl_bat.text()


def test_f2_main_screen_renders_single_vs5_logo_no_overlap(harness: h.AppHarness) -> None:
    from PyQt6.QtCore import QRect

    screen = h.find_widget(harness.window, "main_screen")
    logo_rect = QRect(20, 15, 115, 110)
    img = h.grab_image(screen)
    assert h.count_color_pixels(img, "#226DAA", rect=logo_rect, tolerance=22, stride=1) >= 15
    assert h.count_color_pixels(img, "#1EB5D7", rect=logo_rect, tolerance=22, stride=1) >= 15

    header_widgets = [
        h.find_widget(screen, name)
        for name in ("lbl_active_patient", "lbl_datetime", "lbl_uart_status", "lbl_battery_pct")
    ]
    rects = [h.widget_rect_in_window(w, harness.window) for w in header_widgets]
    for idx_a in range(len(rects)):
        assert not rects[idx_a].intersects(QRect(31, 24, 87, 92)), "Header label overlaps VS5 logo"
        for idx_b in range(idx_a + 1, len(rects)):
            inter = rects[idx_a].intersected(rects[idx_b])
            assert inter.width() <= 2 or inter.height() <= 2


def test_f2_jetbrains_mono_font_applied(harness: h.AppHarness) -> None:
    from PyQt6.QtGui import QFontDatabase

    assert "JetBrains Mono" in set(QFontDatabase.families())
    btn = h.find_widget(harness.window, "btn_patient")
    lbl = h.find_widget(harness.window, "lbl_battery_pct")
    assert "JetBrains Mono" in btn.font().family() or "JetBrains Mono" in lbl.font().family()


# ===========================================================================
# F3: Main Screen Action Bar & Pressed States (6 tests)
# ===========================================================================


def test_f3_bottom_bar_geometry_and_labels(harness: h.AppHarness) -> None:
    expected = {
        "btn_patient": "PATIENT",
        "btn_settings": "SETTINGS",
        "btn_record": "RECORD",
    }
    for name, label in expected.items():
        btn = h.find_widget(harness.window, name)
        assert btn.isVisible()
        assert abs(btn.width() - 212) <= 4
        assert abs(btn.height() - 51) <= 4
        assert label in btn.text().upper()

    assert harness.window.main_screen.findChild(object, "btn_save") is None
    btn_rec = h.find_widget(harness.window, "btn_record")
    assert h.region_has_color(btn_rec, "#FF7F7F", tolerance=20, min_pixels=50)


def test_f3_patient_button_navigates_to_patient_screen(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    patient_screen = h.find_widget(harness.window, "patient_screen")
    main_screen = h.find_widget(harness.window, "main_screen")
    assert patient_screen.isVisible()
    assert not main_screen.isVisible()


def test_f3_settings_button_opens_settings_modal(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None and modal.isVisible()


def test_f3_record_button_shows_recording_state_and_timer(harness: h.AppHarness) -> None:
    btn_rec = h.find_widget(harness.window, "btn_record")
    timer_lbl = h.find_widget(harness.window, "lbl_recording_timer")
    assert not timer_lbl.isVisible()

    h.click_widget(btn_rec)
    h.wait_until(lambda: btn_rec.text() == "RECORDING...", description="recording label")
    assert h.region_has_color(btn_rec, "#90FF93", tolerance=20, min_pixels=50)
    assert timer_lbl.isVisible()
    assert len(timer_lbl.text()) == 12

    h.click_widget(btn_rec)
    h.wait_until(lambda: btn_rec.text() == "RECORD", description="record reset")
    assert not timer_lbl.isVisible()


def test_f3_record_button_toggles_recording_start_and_stop(harness: h.AppHarness) -> None:
    btn_rec = h.find_widget(harness.window, "btn_record")
    h.click_widget(btn_rec)
    h.wait_until(lambda: len(harness.command_handler.record_calls) >= 1, description="record start")
    assert harness.command_handler.record_calls[0][0] is True

    harness.vital_port.set_status(recording_active=True, recording_elapsed_s=5)
    h.pump_events(100)

    h.click_widget(btn_rec)
    h.wait_until(lambda: len(harness.command_handler.record_calls) >= 2, description="record stop")
    assert harness.command_handler.record_calls[1][0] is False


@pytest.mark.parametrize("btn_name", ["btn_patient", "btn_settings"])
def test_f3_neutral_buttons_show_figma_pressed_state(harness: h.AppHarness, btn_name: str) -> None:
    btn = h.find_widget(harness.window, btn_name)
    assert h.region_has_color(btn, "#D9D9D9", tolerance=20, min_pixels=40)
    h.press_and_hold(btn)
    try:
        assert h.region_has_color(btn, "#3F3F3F", tolerance=22, min_pixels=40), (
            f"{btn_name} did not switch to #3F3F3F while pressed"
        )
    finally:
        h.release_widget(btn)
    assert h.region_has_color(btn, "#D9D9D9", tolerance=20, min_pixels=40)


# ===========================================================================
# F4: Patient Screen List & Selection (6 tests)
# ===========================================================================


def test_f4_patient_screen_renders_all_patients_and_header(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    assert ps.isVisible()
    assert "Patient List" in h.joined_text(ps)

    cards = h.find_patient_cards(ps)
    assert len(cards) == 3
    all_text = " ".join(h.joined_text(c) for c in cards)
    for idx in (1, 2, 3):
        assert f"Patient Number {idx}" in all_text
    assert "Age:" in all_text and "Height:" in all_text and "Weight:" in all_text

    uart_lbl = ps.findChild(type(h.find_widget(harness.window, "lbl_battery_pct")), "lbl_uart_status")
    assert uart_lbl is None or not uart_lbl.isVisible()


def test_f4_clicking_patient_card_updates_selection_and_border(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    assert len(cards) >= 2

    h.click_widget(cards[1])
    assert harness.patient_store.get_active_patient().patient_id == "p-2"
    assert h.region_has_color(cards[1], "#226DAA", tolerance=24, stride=1, min_pixels=15)


def test_f4_back_button_returns_to_main_screen_with_selected_patient(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    h.click_widget(h.find_widget(ps, "btn_back"))

    ms = h.find_widget(harness.window, "main_screen")
    assert ms.isVisible()
    assert "Patient Number 2" in h.find_widget(ms, "lbl_active_patient").text()


def test_f4_new_patient_button_opens_blank_dialog(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None and dlg.isVisible()

    for field_name in ("input_patient_name", "input_patient_age", "input_patient_height", "input_patient_weight"):
        edit = h.find_line_edit(h.find_widget(dlg, field_name))
        assert edit.text() == ""


def test_f4_edit_patient_button_opens_prefilled_dialog(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    h.click_widget(h.find_widget(ps, "btn_edit_patient"))

    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None and dlg.isVisible()
    assert h.find_line_edit(h.find_widget(dlg, "input_patient_name")).text() == "Patient Number 2"
    assert "42" in h.find_line_edit(h.find_widget(dlg, "input_patient_age")).text()
    assert "165" in h.find_line_edit(h.find_widget(dlg, "input_patient_height")).text()
    assert "60" in h.find_line_edit(h.find_widget(dlg, "input_patient_weight")).text()


def test_f4_patient_screen_buttons_have_figma_dimensions(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    expected = {
        "btn_back": "BACK",
        "btn_delete_patient": "DELETE",
        "btn_edit_patient": "EDIT PATIENT",
        "btn_new_patient": "NEW PATIENT",
    }
    for name, label in expected.items():
        btn = h.find_widget(ps, name)
        assert btn.isVisible()
        assert abs(btn.width() - 212) <= 4
        assert abs(btn.height() - 51) <= 4
        assert label in btn.text().upper()


# ===========================================================================
# F5: New / Edit Patient Pop Up & Validation (5 tests)
# ===========================================================================


def test_f5_create_valid_patient_saves_to_store_and_updates_list(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    h.type_via_keyboard(harness, "John Doe", press_done=True)

    for fname, val in (("input_patient_age", "36"), ("input_patient_height", "178"), ("input_patient_weight", "70")):
        h.focus_input_field(h.find_widget(dlg, fname))
        h.type_via_keyboard(harness, val, press_done=True)

    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(lambda: h.find_overlay(harness, "new_patient_dialog", require_visible=True) is None, description="dialog close")

    assert harness.patient_store.create_calls == [
        ("John Doe", 36, 178, 70, harness.contracts.Gender.MALE)
    ]
    ps = h.find_widget(harness.window, "patient_screen")
    assert "John Doe" in " ".join(h.joined_text(c) for c in h.find_patient_cards(ps))


def test_f5_edit_valid_patient_updates_store_and_card(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    h.click_widget(h.find_widget(ps, "btn_edit_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    h.clear_input_via_keyboard(harness, name_field)
    h.type_via_keyboard(harness, "Jane Doe", press_done=True)

    wt_field = h.find_widget(dlg, "input_patient_weight")
    h.clear_input_via_keyboard(harness, wt_field)
    h.type_via_keyboard(harness, "62", press_done=True)

    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(lambda: len(harness.patient_store.update_calls) == 1, description="update call")

    pid, name, age, height_cm, weight_kg, gender = harness.patient_store.update_calls[0]
    assert pid == "p-1" and name == "Jane Doe" and weight_kg == 62
    assert age == 34 and height_cm == 170 and gender == harness.contracts.Gender.MALE
    cards_txt = " ".join(h.joined_text(c) for c in h.find_patient_cards(ps))
    assert "Jane Doe" in cards_txt and "62" in cards_txt


def test_f5_cancel_new_patient_discards_without_creating(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    initial_count = len(h.find_patient_cards(ps))
    h.click_widget(h.find_widget(ps, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    h.type_via_keyboard(harness, "Temp", press_done=True)
    h.click_widget(h.find_widget(dlg, "btn_patient_cancel"))

    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is None
    assert harness.patient_store.create_calls == []
    assert len(h.find_patient_cards(ps)) == initial_count


def test_f5_cancel_edit_patient_discards_without_updating(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    h.click_widget(h.find_widget(ps, "btn_edit_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    h.clear_input_via_keyboard(harness, name_field)
    h.type_via_keyboard(harness, "Modified", press_done=True)
    h.click_widget(h.find_widget(dlg, "btn_patient_cancel"))

    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is None
    assert harness.patient_store.update_calls == []
    assert harness.patient_store.get_active_patient().name == "Patient Number 1"


def test_f5_modal_geometry_and_button_colors_match_figma(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    card = h.find_modal_card(dlg, 875, 231)
    assert abs(card.width() - 875) <= 20
    assert abs(card.height() - 231) <= 20

    btn_cancel = h.find_widget(dlg, "btn_patient_cancel")
    btn_save = h.find_widget(dlg, "btn_patient_save")
    assert h.region_has_color(btn_cancel, "#FF7F7F", tolerance=20, min_pixels=40)
    assert h.region_has_color(btn_save, "#90FF93", tolerance=20, min_pixels=40)


# ===========================================================================
# F6: Settings Modal (SETTINGS 1-8) (6 tests)
# ===========================================================================


def test_f6_settings_modal_displays_all_8_slots(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None

    card = h.find_modal_card(modal, 669, 437)
    assert abs(card.width() - 669) <= 24
    assert abs(card.height() - 437) <= 24

    scroll = h.find_widget(modal, "settings_scroll_area")
    for idx in range(1, 9):
        row = h.find_widget(scroll, f"settings_row_{idx}")
        assert f"SETTINGS {idx}" in h.joined_text(row)


def test_f6_settings_toggle_off_to_on_updates_store_and_color(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row1 = h.find_widget(modal, "settings_row_1")
    ctrl = h.find_settings_row_control(row1)
    h.click_widget(ctrl)

    assert (1, True) in harness.settings_store.update_calls
    assert "ON" in h.joined_text(row1).upper()
    assert h.region_has_color(row1, "#90FF93", tolerance=22, min_pixels=15)


def test_f6_settings_toggle_on_to_off_updates_store_and_color(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row2 = h.find_widget(modal, "settings_row_2")
    ctrl = h.find_settings_row_control(row2)
    h.click_widget(ctrl)

    assert (2, False) in harness.settings_store.update_calls
    assert "OFF" in h.joined_text(row2).upper()
    assert h.region_has_color(row2, "#FF6161", tolerance=22, min_pixels=15)


def test_f6_settings_value_slot_updates_via_numpad(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row3 = h.find_widget(modal, "settings_row_3")
    ctrl = h.find_settings_row_control(row3)
    h.click_widget(ctrl)
    h.pump_events(60)

    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    assert h.keyboard_mode(kb) == "numpad"
    for _ in range(4):
        h.tap_keyboard_key(kb, "BACKSPACE")
    h.type_via_keyboard(harness, "125", press_done=True)
    h.pump_events(60)

    assert any(slot == 3 and str(val) == "125" for slot, val in harness.settings_store.update_calls)
    assert "125" in h.joined_text(row3)


def test_f6_settings_dropdown_slot_selects_option(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row4 = h.find_widget(modal, "settings_row_4")
    h.select_settings_dropdown(harness, row4, "Option B")

    assert any(slot == 4 and val == "Option B" for slot, val in harness.settings_store.update_calls)
    assert "Option B" in h.joined_text(row4)


def test_f6_settings_close_button_dismisses_modal(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None
    h.click_widget(h.find_widget(modal, "btn_settings_close"))
    assert h.find_overlay(harness, "settings_modal", require_visible=True) is None

    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    assert h.find_widget(harness.window, "patient_screen").isVisible()


# ===========================================================================
# F7: On-Screen Virtual Keyboard & Numpad (5 tests)
# ===========================================================================


def test_f7_focusing_name_field_opens_qwerty_keyboard(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and kb.isVisible()
    assert h.keyboard_mode(kb) == "qwerty"


@pytest.mark.parametrize("field_name", ["input_patient_age", "input_patient_height", "input_patient_weight"])
def test_f7_focusing_numeric_fields_opens_numpad_keyboard(harness: h.AppHarness, field_name: str) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    h.focus_input_field(h.find_widget(dlg, field_name))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and kb.isVisible()
    assert h.keyboard_mode(kb) == "numpad"


def test_f7_qwerty_typing_space_and_shift_updates_name(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    h.focus_input_field(name_field)
    h.type_via_keyboard(harness, "John Doe", press_done=False)
    assert h.find_line_edit(name_field).text() == "John Doe"


def test_f7_numpad_typing_populates_age_height_weight(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    for fname, digits in (("input_patient_age", "36"), ("input_patient_height", "178"), ("input_patient_weight", "70")):
        field = h.find_widget(dlg, fname)
        h.focus_input_field(field)
        h.type_via_keyboard(harness, digits, press_done=True)
        assert h.find_line_edit(field).text() == digits


def test_f7_keyboard_backspace_and_done_work(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    h.focus_input_field(name_field)
    h.type_via_keyboard(harness, "ABC", press_done=False)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    h.tap_keyboard_key(kb, "BACKSPACE")
    assert h.find_line_edit(name_field).text() == "AB"

    h.tap_keyboard_key(kb, "DONE")
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None


# ===========================================================================
# F8: Touch-Friendly Drag Scrolling (5 tests)
# ===========================================================================


def test_f8_patient_list_drag_down_scrolls_viewport(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    assert scroll.verticalScrollBar().value() == 0

    h.touch_drag(scroll, dy_px=-200)
    assert scroll.verticalScrollBar().value() > 0


def test_f8_patient_list_drag_up_scrolls_back_to_top(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    h.touch_drag(scroll, dy_px=-220)
    scrolled = scroll.verticalScrollBar().value()
    assert scrolled > 0

    h.touch_drag(scroll, dy_px=260)
    assert scroll.verticalScrollBar().value() < scrolled


def test_f8_patient_list_drag_does_not_mis_select_card(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    initial_active = ah.patient_store.get_active_patient().patient_id

    h.touch_drag(scroll, dy_px=-180, start_ratio=(0.5, 0.45))
    assert scroll.verticalScrollBar().value() > 0
    assert ah.patient_store.get_active_patient().patient_id == initial_active


def test_f8_settings_modal_drag_scrolls_to_row_8(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None
    scroll = h.find_widget(modal, "settings_scroll_area")
    row8 = h.find_widget(scroll, "settings_row_8")

    h.scroll_into_view_via_drag(scroll, row8)
    vp = scroll.viewport()
    center_in_vp = row8.mapTo(vp, row8.rect().center())
    assert 0 <= center_in_vp.y() <= vp.height()


def test_f8_settings_modal_drag_does_not_toggle_rows(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None
    scroll = h.find_widget(modal, "settings_scroll_area")

    h.touch_drag(scroll, dy_px=-150, start_ratio=(0.82, 0.25))
    assert harness.settings_store.update_calls == []


# ===========================================================================
# F9: Desktop Windowed & RPi 5 Kiosk Shell (5 tests)
# ===========================================================================


def test_f9_create_app_windowed_mode_fixed_1280x720(make_app: object) -> None:
    ah = make_app(kiosk=False)
    assert ah.window.width() == 1280
    assert ah.window.height() == 720
    assert not ah.window.isFullScreen()


def test_f9_create_app_kiosk_mode_fullscreen(make_app: object) -> None:
    ah = make_app(kiosk=True)
    assert ah.window.isFullScreen()


def test_f9_f11_toggles_fullscreen_kiosk_mode(make_app: object) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    ah = make_app(kiosk=False)
    assert not ah.window.isFullScreen()
    QTest.keyClick(ah.window, Qt.Key.Key_F11)
    h.pump_events(60)
    assert ah.window.isFullScreen()


def test_f9_cli_help_documents_expected_flags() -> None:
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(h.SRC_DIR) if not existing_pp else f"{h.SRC_DIR}{os.pathsep}{existing_pp}"
    proc = subprocess.run(
        [sys.executable, "-m", "vitalsense5", "--help"],
        cwd=str(h.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    for flag in ("--windowed", "--kiosk", "--mock", "--tick-ms"):
        assert flag in proc.stdout, f"CLI --help missing {flag}"


def test_f9_cli_main_windowed_launches_and_exits_cleanly(qapp: object) -> None:
    from PyQt6.QtCore import QTimer

    main_mod = h.load_main_module()
    QTimer.singleShot(120, qapp.quit)
    rc = main_mod.main(["--windowed", "--mock", "--tick-ms", "20"])
    for top in list(qapp.topLevelWidgets()):
        top.close()
        top.deleteLater()
    qapp.processEvents()
    assert rc == 0


# ===========================================================================
# F10: Swappable Adapter Boundary & Device/Alarm States (5 tests)
# ===========================================================================


def test_f10_swappable_custom_adapter_drives_ui(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    cols = {name: h.find_widget(screen, name) for name in ("vital_prv", "vital_rr", "vital_pi", "vital_spo2", "vital_bp")}
    before_imgs = {name: h.grab_image(col) for name, col in cols.items()}

    harness.vital_port.push_vitals(
        prv_rmssd_ms=55.0,
        rr_brpm=21.0,
        pi_percent=2.5,
        spo2_percent=94.0,
        bp_sys_mmhg=135,
        bp_dia_mmhg=88,
    )
    h.pump_events(120)

    _assert_vital_value_rendered(cols["vital_prv"], ("55",), before_imgs["vital_prv"])
    _assert_vital_value_rendered(cols["vital_rr"], ("21",), before_imgs["vital_rr"])
    _assert_vital_value_rendered(cols["vital_pi"], ("2.5", "02", "2"), before_imgs["vital_pi"])
    _assert_vital_value_rendered(cols["vital_spo2"], ("94",), before_imgs["vital_spo2"])
    _assert_vital_value_rendered(cols["vital_bp"], ("135", "88"), before_imgs["vital_bp"])


def test_f10_sensor_finger_off_shows_indicator_and_suppresses_trace(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    ppg = h.find_widget(screen, "ppg_canvas")
    before_ppg = h.grab_image(ppg)

    harness.vital_port.set_status(sensor_state=harness.contracts.SensorState.FINGER_OFF)
    h.pump_events(150)

    txt = h.joined_text(screen).lower()
    after_ppg = h.grab_image(ppg)
    assert (
        "finger" in txt
        or "detached" in txt
        or "no signal" in txt
        or "sensor" in txt
        or h.images_differ(before_ppg, after_ppg)
    )


def test_f10_uart_disconnect_shows_status_and_stale_dashes(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    lbl_uart = h.find_widget(screen, "lbl_uart_status")
    before_spo2 = h.grab_image(h.find_widget(screen, "vital_spo2"))

    harness.vital_port.set_status(
        uart_state=harness.contracts.ConnectionState.DISCONNECTED,
        esp32_state=harness.contracts.ConnectionState.DISCONNECTED,
    )
    harness.vital_port.push_vitals(
        prv_rmssd_ms=None,
        rr_brpm=None,
        pi_percent=None,
        spo2_percent=None,
        bp_sys_mmhg=None,
        bp_dia_mmhg=None,
    )
    h.pump_events(150)

    uart_txt = lbl_uart.text().lower()
    assert "disconnect" in uart_txt or "offline" in uart_txt or "error" in uart_txt
    _assert_vital_value_rendered(h.find_widget(screen, "vital_spo2"), ("--",), before_spo2)


def test_f10_cloud_offline_updates_status_indicator(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    before_header = h.grab_image(screen)
    before_text = h.joined_text(screen)

    harness.vital_port.set_status(cloud_state=harness.contracts.CloudState.OFFLINE)
    h.pump_events(140)

    after_header = h.grab_image(screen)
    after_text = h.joined_text(screen)
    assert after_text != before_text or h.images_differ(before_header, after_header)


def test_f10_critical_alarm_and_low_battery_render_warnings(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    spo2_col = h.find_widget(screen, "vital_spo2")
    before_spo2 = h.grab_image(spo2_col)
    before_screen = h.grab_image(screen)

    harness.vital_port.set_status(battery_percent=15, battery_voltage=6.8, is_charging=False)
    harness.vital_port.push_vitals(
        spo2_percent=82.0,
        alarms={
            "PRV": harness.contracts.AlarmLevel.NORMAL,
            "RR": harness.contracts.AlarmLevel.NORMAL,
            "PI": harness.contracts.AlarmLevel.NORMAL,
            "SpO2": harness.contracts.AlarmLevel.CRITICAL,
            "BP": harness.contracts.AlarmLevel.NORMAL,
        },
    )
    h.pump_events(150)

    assert "15%" in h.find_widget(screen, "lbl_battery_pct").text()
    _assert_vital_value_rendered(spo2_col, ("82",), before_spo2)
    after_screen = h.grab_image(screen)
    assert h.images_differ(before_screen, after_screen)
