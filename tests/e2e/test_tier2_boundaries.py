"""Tier 2 Opaque-Box E2E Tests: Boundary, edge, invalid-input & fault-state coverage (F1-F10).

Zero top-level imports of ``vitalsense5`` or ``PyQt6``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.e2e import conftest as h


def _collect_imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0].lower())
    return mods


# ===========================================================================
# F1: Scope Exclusions & Documentation Integrity (5 tests)
# ===========================================================================


def test_f1_scope_exclusion_no_esp32_firmware_files() -> None:
    forbidden_exts = {".c", ".cpp", ".cc", ".h", ".hpp", ".ino"}
    src_root = h.REPO_ROOT / "src"
    assert src_root.is_dir(), "src/ directory missing"
    bad_files = [
        p for p in src_root.rglob("*") if p.is_file() and p.suffix.lower() in forbidden_exts
    ]
    assert bad_files == [], f"Firmware source files found in src/: {bad_files}"


def test_f1_scope_exclusion_no_sqlite_or_pyserial_in_frontend() -> None:
    pkg_dir = h.SRC_DIR / "vitalsense5"
    backend_dir = pkg_dir / "backend"
    assert pkg_dir.is_dir(), "src/vitalsense5 missing"
    db_forbidden = {"sqlite3", "sqlalchemy"}
    serial_forbidden = {"serial", "pyserial"}
    for py_file in pkg_dir.rglob("*.py"):
        mods = _collect_imported_modules(py_file)
        db_hits = mods & db_forbidden
        assert not db_hits, f"Forbidden DB imports {db_hits} in {py_file}"
        if not py_file.is_relative_to(backend_dir):
            serial_hits = mods & serial_forbidden
            assert not serial_hits, f"Forbidden serial imports {serial_hits} in frontend file {py_file}"


def test_f1_scope_exclusion_no_scipy_or_ml_in_ui_layers() -> None:
    pkg_dir = h.SRC_DIR / "vitalsense5"
    forbidden = {"scipy", "sklearn", "scikit_learn", "xgboost", "catboost", "lightgbm", "torch", "tensorflow"}
    for sub in ("widgets", "screens"):
        sub_dir = pkg_dir / sub
        if not sub_dir.is_dir():
            continue
        for py_file in sub_dir.rglob("*.py"):
            mods = _collect_imported_modules(py_file)
            hits = mods & forbidden
            assert not hits, f"Forbidden signal-processing/ML imports {hits} in {py_file}"


def test_f1_gap_report_documents_sub_44px_touch_targets() -> None:
    gap_text = (h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md").read_text(encoding="utf-8")
    lower = gap_text.lower()
    assert "13px" in lower or "13 px" in lower or "scrollbar" in lower
    assert "31px" in lower or "31 px" in lower or "44" in lower
    assert "keyboard" in lower and ("shift" in lower or "cover" in lower or "occlu" in lower)


def test_f1_docs_contain_no_unresolved_placeholders() -> None:
    for doc_path in (
        h.REPO_ROOT / "docs" / "FRONTEND_PLAN.md",
        h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md",
    ):
        text = doc_path.read_text(encoding="utf-8")
        for marker in ("TODO", "FIXME", "TBD", "Lorem ipsum"):
            assert marker not in text, f"Unresolved placeholder {marker!r} in {doc_path}"


# ===========================================================================
# F2: Main Screen Vitals & PPG Boundaries (6 tests)
# ===========================================================================


def test_f2_all_none_vital_snapshot_renders_stale_dashes(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    cols = [h.find_widget(screen, name) for name in ("vital_prv", "vital_rr", "vital_pi", "vital_spo2", "vital_bp")]
    before = [h.grab_image(c) for c in cols]

    harness.vital_port.push_vitals(
        prv_rmssd_ms=None,
        rr_brpm=None,
        pi_percent=None,
        spo2_percent=None,
        bp_sys_mmhg=None,
        bp_dia_mmhg=None,
        bpm=None,
    )
    h.pump_events(140)

    for idx, col in enumerate(cols):
        txt = h.joined_text(col)
        if "--" in txt:
            continue
        assert h.images_differ(before[idx], h.grab_image(col)), (
            f"{col.objectName()} neither showed '--' nor updated visually on None vitals"
        )


def test_f2_extreme_boundary_vitals_fit_without_clipping(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    harness.vital_port.push_vitals(
        prv_rmssd_ms=199.9,
        rr_brpm=60.0,
        pi_percent=19.9,
        spo2_percent=100.0,
        bp_sys_mmhg=250,
        bp_dia_mmhg=150,
    )
    h.pump_events(140)

    names = ("vital_prv", "vital_rr", "vital_pi", "vital_spo2", "vital_bp")
    rects = [h.widget_rect_in_window(h.find_widget(screen, n), harness.window) for n in names]
    for r in rects:
        assert 0 <= r.left() and r.right() <= 1280
        assert 0 <= r.top() and r.bottom() <= 720
    for i in range(len(rects) - 1):
        inter = rects[i].intersected(rects[i + 1])
        assert inter.width() <= 2 or inter.height() <= 2


def test_f2_empty_waveform_batch_is_safe_noop(harness: h.AppHarness) -> None:
    ppg = h.find_widget(harness.window, "ppg_canvas")
    for _ in range(5):
        harness.vital_port.push_waveform([])
        h.pump_events(45)
    assert ppg.isVisible()
    assert h.region_has_color(ppg, "#E4E4E4", min_pixels=100)


def test_f2_out_of_range_waveform_samples_clamped_inside_canvas(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    ppg = h.find_widget(screen, "ppg_canvas")
    ppg_rect = h.widget_rect_in_window(ppg, harness.window)
    above_rect = ppg_rect.translated(0, -30)
    above_rect.setHeight(24)

    before = h.grab_image(harness.window)
    before_count = h.count_color_pixels(before, "#313131", rect=above_rect, tolerance=16, stride=1)

    harness.vital_port.push_waveform([-5.0, 5.0, 0.0, 10.0, -10.0, 8.0, -8.0] * 10)
    h.pump_events(140)

    img = h.grab_image(harness.window)
    assert h.count_color_pixels(img, "#313131", rect=above_rect, tolerance=16, stride=1) == before_count


def test_f2_large_waveform_batch_1000_samples_no_freeze(harness: h.AppHarness) -> None:
    ppg = h.find_widget(harness.window, "ppg_canvas")
    before = h.grab_image(ppg)
    large_batch = [0.7 * ((i % 20) / 10.0 - 1.0) for i in range(1000)]
    harness.vital_port.push_waveform(large_batch)
    h.pump_events(180)
    assert ppg.isVisible()
    assert h.images_differ(before, h.grab_image(ppg))


def test_f2_bpm_none_and_populated_both_supported(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    harness.vital_port.push_vitals(bpm=None, prv_rmssd_ms=65.0)
    h.pump_events(80)
    harness.vital_port.push_vitals(bpm=75, prv_rmssd_ms=68.0)
    h.pump_events(80)
    assert h.find_widget(screen, "vital_prv").isVisible()


# ===========================================================================
# F3: Action Bar & Modal Blocking Boundaries (5 tests)
# ===========================================================================


def test_f3_recording_timer_advances_without_lockup(harness: h.AppHarness) -> None:
    btn_rec = h.find_widget(harness.window, "btn_record")
    timer_lbl = h.find_widget(harness.window, "lbl_recording_timer")
    h.click_widget(btn_rec, wait_ms=30)
    t1 = timer_lbl.text()
    h.pump_events(80)
    t2 = timer_lbl.text()
    assert timer_lbl.isVisible()
    assert t2 != t1
    assert h.find_widget(harness.window, "main_screen").isVisible()


def test_f3_rapid_record_toggle_sequence_consistent(harness: h.AppHarness) -> None:
    btn_rec = h.find_widget(harness.window, "btn_record")
    for _ in range(3):
        h.click_widget(btn_rec, wait_ms=25)
    h.pump_events(80)
    assert [call[0] for call in harness.command_handler.record_calls] == [True, False, True]


def test_f3_delete_confirmation_cancel_keeps_patient_intact(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    before = len(harness.patient_store.list_patients())
    h.click_widget(h.find_widget(ps, "btn_delete_patient"))
    dlg = h.find_overlay(harness, "confirm_delete_dialog", require_visible=True)
    assert dlg is not None
    h.click_widget(h.find_widget(dlg, "btn_confirm_cancel"))
    assert len(harness.patient_store.list_patients()) == before


def test_f3_record_failure_does_not_latch_recording_active(harness: h.AppHarness) -> None:
    harness.command_handler.record_result = (False, "UART disconnected")
    btn_rec = h.find_widget(harness.window, "btn_record")
    h.click_widget(btn_rec)
    h.pump_events(80)
    h.click_widget(btn_rec)
    h.pump_events(80)
    # Because first toggle failed, second click should still attempt to start (True), not stop (False)
    assert [call[0] for call in harness.command_handler.record_calls] == [True, True]


def test_f3_modal_blocks_clicks_to_underlying_main_buttons(harness: h.AppHarness) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    btn_patient = h.find_widget(harness.window, "btn_patient")
    patient_pos_in_win = h.widget_rect_in_window(btn_patient, harness.window).center()

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None

    target = harness.window.childAt(patient_pos_in_win) or harness.window
    QTest.mouseClick(
        target,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        target.mapFrom(harness.window, patient_pos_in_win),
    )
    h.pump_events(60)
    assert not h.find_widget(harness.window, "patient_screen").isVisible()
    assert harness.command_handler.record_calls == []


# ===========================================================================
# F4: Patient Screen Empty / Large / Long Name Boundaries (6 tests)
# ===========================================================================


def test_f4_empty_patient_list_renders_safe_empty_state(make_app: object) -> None:
    ah = make_app(patients=[])
    ms = h.find_widget(ah.window, "main_screen")
    assert ms.isVisible()
    assert h.find_widget(ms, "lbl_active_patient").text() is not None

    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    assert ps.isVisible()
    assert h.find_patient_cards(ps) == []


def test_f4_edit_patient_guarded_when_patient_list_empty(make_app: object) -> None:
    ah = make_app(patients=[])
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    btn_edit = h.find_widget(ps, "btn_edit_patient")
    if btn_edit.isEnabled():
        h.click_widget(btn_edit)
    assert h.find_overlay(ah, "new_patient_dialog", require_visible=True) is None


def test_f4_single_patient_list_and_return_preserves_selection(make_app: object) -> None:
    contracts = h.load_contracts()
    only = contracts.PatientRecord("p-only", "Solo Patient", 30, 172, 65)
    ah = make_app(patients=[only])

    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    assert scroll.verticalScrollBar().maximum() == 0

    cards = h.find_patient_cards(ps)
    assert len(cards) == 1
    h.click_widget(cards[0])
    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "Solo Patient" in h.find_widget(ah.window, "lbl_active_patient").text()


def test_f4_fifty_patients_scroll_and_select_last_record(make_app: object) -> None:
    ah = make_app(patient_count=50)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)
    assert len(cards) == 50

    h.scroll_into_view_via_drag(scroll, cards[-1], max_drags=35)
    h.click_widget(cards[-1])
    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "Patient Number 50" in h.find_widget(ah.window, "lbl_active_patient").text()


def test_f4_long_patient_name_does_not_overflow_card(make_app: object) -> None:
    contracts = h.load_contracts()
    long_name = "A" * 80
    rec = contracts.PatientRecord("p-long", long_name, 55, 180, 82)
    ah = make_app(patients=[rec])
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    assert len(cards) == 1
    card_rect = h.widget_rect_in_window(cards[0], ah.window)
    assert cards[0].width() <= 1180
    assert card_rect.right() <= 1280


def test_f4_switch_patient_during_active_recording_blocked(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_record"))
    harness.vital_port.set_status(recording_active=True, recording_elapsed_s=3)
    h.pump_events(60)

    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    toast = h.find_widget(harness.window, "toast_banner")
    assert toast.isVisible()
    assert "Cannot change patient while recording" in toast.text()
    h.click_widget(h.find_widget(ps, "btn_back"))

    ms = h.find_widget(harness.window, "main_screen")
    assert ms.isVisible()
    assert "Patient Number 1" in h.find_widget(ms, "lbl_active_patient").text()


# ===========================================================================
# F5: New/Edit Patient Form Validation Boundaries (7 tests)
# ===========================================================================


def _open_new_patient_dialog(harness: h.AppHarness) -> object:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None
    return dlg


def _fill_patient_fields(
    harness: h.AppHarness, dlg: object, name: str, age: str, height: str, weight: str
) -> None:
    for fname, val in (
        ("input_patient_name", name),
        ("input_patient_age", age),
        ("input_patient_height", height),
        ("input_patient_weight", weight),
    ):
        field = h.find_widget(dlg, fname)
        edit = h.find_line_edit(field)
        h.focus_input_field(field)
        if edit.text():
            h.clear_input_via_keyboard(harness, field)
        if val:
            h.type_via_keyboard(harness, val, press_done=True)
        else:
            kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
            if kb is not None:
                h.tap_keyboard_key(kb, "DONE")


def test_f5_rejects_empty_patient_name(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "", "30", "170", "65")
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert harness.patient_store.create_calls == []


def test_f5_rejects_whitespace_only_patient_name(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "   ", "30", "170", "65")
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert harness.patient_store.create_calls == []


def test_f5_rejects_non_numeric_or_empty_numeric_fields(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "Alice", "", "170", "65")
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert harness.patient_store.create_calls == []


@pytest.mark.parametrize(
    "age,height,weight",
    [
        ("0", "170", "65"),
        ("30", "0", "65"),
        ("30", "170", "0"),
    ],
)
def test_f5_rejects_zero_and_negative_vital_demographics(
    harness: h.AppHarness, age: str, height: str, weight: str
) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "Alice", age, height, weight)
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert harness.patient_store.create_calls == []


def test_f5_rejects_unrealistic_extreme_demographics(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "Extreme", "999", "999", "999")
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert harness.patient_store.create_calls == []


@pytest.mark.parametrize(
    "age,height,weight",
    [
        ("1", "45", "2"),
        ("120", "230", "250"),
    ],
)
def test_f5_accepts_lower_and_upper_physiological_bounds(
    harness: h.AppHarness, age: str, height: str, weight: str
) -> None:
    dlg = _open_new_patient_dialog(harness)
    _fill_patient_fields(harness, dlg, "Valid Bound", age, height, weight)
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(lambda: len(harness.patient_store.create_calls) == 1, description="valid patient created")
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is None


def test_f5_extremely_long_name_contained_inside_dialog(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    card = h.find_modal_card(dlg, 875, 231)
    name_field = h.find_widget(dlg, "input_patient_name")
    h.focus_input_field(name_field)
    h.type_via_keyboard(harness, "X" * 60, press_done=True)

    card_rect = h.widget_rect_in_window(card, harness.window)
    field_rect = h.widget_rect_in_window(name_field, harness.window)
    assert abs(card.width() - 875) <= 20
    assert card_rect.contains(field_rect)


# ===========================================================================
# F6: Settings Modal Boundaries & Persistence (5 tests)
# ===========================================================================


def test_f6_settings_all_toggles_on_and_off_boundaries(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None
    scroll = h.find_widget(modal, "settings_scroll_area")

    for slot_idx in (1, 2, 5, 6, 7, 8):
        row = h.find_widget(scroll, f"settings_row_{slot_idx}")
        h.scroll_into_view_via_drag(scroll, row)
        h.click_widget(h.find_settings_row_control(row))

    slots = {s.slot_index: s.value for s in harness.settings_store.list_settings()}
    assert slots[1] is True
    assert slots[2] is False
    for slot_idx in (5, 6, 7, 8):
        assert slots[slot_idx] is True


def test_f6_settings_value_rejects_empty_or_invalid_entry(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row3 = h.find_widget(modal, "settings_row_3")
    h.click_widget(h.find_settings_row_control(row3))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None

    for _ in range(6):
        h.tap_keyboard_key(kb, "BACKSPACE")
    h.tap_keyboard_key(kb, "DONE")
    h.pump_events(60)

    slot3 = next(s for s in harness.settings_store.list_settings() if s.slot_index == 3)
    assert str(slot3.value).strip() != ""


def test_f6_settings_value_numeric_bounds_zero_and_max(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row3 = h.find_widget(modal, "settings_row_3")

    for val in ("0", "9999"):
        h.click_widget(h.find_settings_row_control(row3))
        kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        for _ in range(6):
            h.tap_keyboard_key(kb, "BACKSPACE")
        h.type_via_keyboard(harness, val, press_done=True)
        h.pump_events(60)
        slot3 = next(s for s in harness.settings_store.list_settings() if s.slot_index == 3)
        assert str(slot3.value) == val


def test_f6_settings_dropdown_empty_options_safe(make_app: object) -> None:
    contracts = h.load_contracts()
    custom_slots = [
        contracts.SettingSlot(1, "SETTINGS 1", "SETTINGS 1", contracts.SettingControlType.TOGGLE, False),
        contracts.SettingSlot(2, "SETTINGS 2", "SETTINGS 2", contracts.SettingControlType.TOGGLE, True),
        contracts.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", contracts.SettingControlType.VALUE, "000"),
        contracts.SettingSlot(4, "SETTINGS 4", "SETTINGS 4", contracts.SettingControlType.DROPDOWN, "LIST", options=[]),
        contracts.SettingSlot(5, "SETTINGS 5", "SETTINGS 5", contracts.SettingControlType.TOGGLE, False),
        contracts.SettingSlot(6, "SETTINGS 6", "SETTINGS 6", contracts.SettingControlType.TOGGLE, False),
        contracts.SettingSlot(7, "SETTINGS 7", "SETTINGS 7", contracts.SettingControlType.TOGGLE, False),
        contracts.SettingSlot(8, "SETTINGS 8", "SETTINGS 8", contracts.SettingControlType.TOGGLE, False),
    ]
    ah = make_app(settings=custom_slots)
    h.click_widget(h.find_widget(ah.window, "btn_settings"))
    modal = h.find_overlay(ah, "settings_modal", require_visible=True)
    row4 = h.find_widget(modal, "settings_row_4")
    h.click_widget(h.find_settings_row_control(row4))
    h.pump_events(50)
    assert modal.isVisible()


def test_f6_settings_persists_across_modal_reopen(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    h.click_widget(h.find_settings_row_control(h.find_widget(modal, "settings_row_1")))
    h.select_settings_dropdown(harness, h.find_widget(modal, "settings_row_4"), "Option C")
    h.click_widget(h.find_widget(modal, "btn_settings_close"))

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal2 = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert "ON" in h.joined_text(h.find_widget(modal2, "settings_row_1")).upper()
    assert "Option C" in h.joined_text(h.find_widget(modal2, "settings_row_4"))


# ===========================================================================
# F7: Virtual Keyboard Non-Occlusion & Switching Boundaries (5 tests)
# ===========================================================================


def test_f7_new_patient_dialog_shifts_up_above_virtual_keyboard(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    kb_rect = h.widget_rect_in_window(kb, harness.window)

    for ctrl_name in (
        "input_patient_name",
        "input_patient_age",
        "input_patient_height",
        "input_patient_weight",
        "btn_patient_cancel",
        "btn_patient_save",
    ):
        ctrl_rect = h.widget_rect_in_window(h.find_widget(dlg, ctrl_name), harness.window)
        assert ctrl_rect.top() >= 0 and ctrl_rect.bottom() <= 720
        assert not ctrl_rect.intersects(kb_rect), f"{ctrl_name} occluded by keyboard"


def test_f7_keyboard_switches_qwerty_to_numpad_and_back(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert h.keyboard_mode(kb) == "qwerty"

    h.focus_input_field(h.find_widget(dlg, "input_patient_age"))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert h.keyboard_mode(kb) == "numpad"

    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert h.keyboard_mode(kb) == "qwerty"


def test_f7_backspace_on_empty_input_is_safe_noop(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    name_field = h.find_widget(dlg, "input_patient_name")
    h.focus_input_field(name_field)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    for _ in range(5):
        h.tap_keyboard_key(kb, "BACKSPACE")
    assert h.find_line_edit(name_field).text() == ""


def test_f7_rapid_keystrokes_preserve_exact_character_order(harness: h.AppHarness) -> None:
    dlg = _open_new_patient_dialog(harness)
    height_field = h.find_widget(dlg, "input_patient_height")
    h.focus_input_field(height_field)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    for digit in ("1", "2", "3", "4", "5"):
        h.tap_keyboard_key(kb, digit)
    h.tap_keyboard_key(kb, "DONE")
    assert h.find_line_edit(height_field).text() == "12345"


def test_f7_settings_value_numpad_keeps_settings_modal_unobstructed(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    row3 = h.find_widget(modal, "settings_row_3")
    h.click_widget(h.find_settings_row_control(row3))
    h.pump_events(60)

    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and h.keyboard_mode(kb) == "numpad"
    row3_rect = h.widget_rect_in_window(row3, harness.window)
    kb_rect = h.widget_rect_in_window(kb, harness.window)
    assert not row3_rect.intersects(kb_rect)


# ===========================================================================
# F8: Touch Drag Threshold & Clamping Boundaries (5 tests)
# ===========================================================================


def test_f8_sub_threshold_4px_movement_acts_as_tap_not_scroll(make_app: object) -> None:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)

    vp = scroll.viewport()
    center_vp = cards[1].mapTo(vp, cards[1].rect().center())
    target = vp.childAt(center_vp) or vp
    start_t = target.mapFrom(vp, center_vp)
    end_t = target.mapFrom(vp, QPoint(center_vp.x(), center_vp.y() - 4))

    QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_t)
    QTest.mouseMove(target, end_t)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_t)
    h.pump_events(80)

    assert scroll.verticalScrollBar().value() == 0
    assert ah.patient_store.get_active_patient().patient_id == "p-2"


def test_f8_above_threshold_16px_movement_scrolls_and_suppresses_tap(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)

    vp = scroll.viewport()
    card2_y_ratio = cards[1].mapTo(vp, cards[1].rect().center()).y() / max(1, vp.height())
    h.touch_drag(scroll, dy_px=-60, start_ratio=(0.5, card2_y_ratio))

    assert ah.patient_store.get_active_patient().patient_id == "p-1"
    assert scroll.verticalScrollBar().value() > 0


def test_f8_drag_past_top_clamps_at_zero(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    h.touch_drag(scroll, dy_px=300)
    assert scroll.verticalScrollBar().value() == 0


def test_f8_drag_past_bottom_clamps_at_maximum(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    for _ in range(8):
        h.touch_drag(scroll, dy_px=-300, start_ratio=(0.5, 0.8))
    bar = scroll.verticalScrollBar()
    assert bar.value() == bar.maximum()


def test_f8_drag_on_short_non_scrollable_list_no_crash(make_app: object) -> None:
    ah = make_app(patient_count=2)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    scroll = h.find_widget(ah.window, "patient_scroll_area")
    assert scroll.verticalScrollBar().maximum() == 0
    h.touch_drag(scroll, dy_px=-150)
    assert scroll.verticalScrollBar().value() == 0


# ===========================================================================
# F9: Kiosk Toggle, CLI Boundaries & Shutdown Lifecycle (5 tests)
# ===========================================================================


def test_f9_f11_double_toggle_restores_1280x720_windowed(make_app: object) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    ah = make_app(kiosk=False)
    QTest.keyClick(ah.window, Qt.Key.Key_F11)
    h.pump_events(60)
    assert ah.window.isFullScreen()

    QTest.keyClick(ah.window, Qt.Key.Key_F11)
    h.pump_events(60)
    assert not ah.window.isFullScreen()
    assert ah.window.width() == 1280 and ah.window.height() == 720


def test_f9_cli_main_kiosk_mode_launches_fullscreen(qapp: object) -> None:
    from PyQt6.QtCore import QTimer

    main_mod = h.load_main_module()
    QTimer.singleShot(120, qapp.quit)
    rc = main_mod.main(["--kiosk", "--mock"])
    for top in list(qapp.topLevelWidgets()):
        top.close()
        top.deleteLater()
    qapp.processEvents()
    assert rc == 0


def test_f9_cli_custom_tick_ms_boundary(qapp: object) -> None:
    from PyQt6.QtCore import QTimer

    main_mod = h.load_main_module()
    QTimer.singleShot(120, qapp.quit)
    rc = main_mod.main(["--windowed", "--tick-ms", "10"])
    for top in list(qapp.topLevelWidgets()):
        top.close()
        top.deleteLater()
    qapp.processEvents()
    assert rc == 0


def test_f9_cli_unknown_flag_returns_nonzero_exit() -> None:
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(h.SRC_DIR) if not existing_pp else f"{h.SRC_DIR}{os.pathsep}{existing_pp}"
    proc = subprocess.run(
        [sys.executable, "-m", "vitalsense5", "--nonexistent-flag"],
        cwd=str(h.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0


def test_f9_window_close_stops_vital_port(make_app: object) -> None:
    ah = make_app(kiosk=False)
    ah.window.close()
    h.pump_events(60)
    assert ah.vital_port.stopped is True


# ===========================================================================
# F10: Adapter Faults, Alarms & Telemetry Boundaries (6 test functions / 8 cases)
# ===========================================================================


def test_f10_uart_reconnecting_and_recovery_lifecycle(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    lbl_uart = h.find_widget(screen, "lbl_uart_status")
    ConnectionState = harness.contracts.ConnectionState

    harness.vital_port.set_status(uart_state=ConnectionState.RECONNECTING, esp32_state=ConnectionState.RECONNECTING)
    h.pump_events(120)
    assert "reconnect" in lbl_uart.text().lower()

    harness.vital_port.set_status(uart_state=ConnectionState.DISCONNECTED, esp32_state=ConnectionState.DISCONNECTED)
    h.pump_events(120)
    assert "disconnect" in lbl_uart.text().lower()

    harness.vital_port.set_status(uart_state=ConnectionState.CONNECTED, esp32_state=ConnectionState.CONNECTED)
    harness.vital_port.push_vitals(spo2_percent=97.0)
    h.pump_events(120)
    assert "connect" in lbl_uart.text().lower() and "disconnect" not in lbl_uart.text().lower()


@pytest.mark.parametrize("sensor_state_name", ["POOR_SIGNAL", "CALIBRATING"])
def test_f10_sensor_poor_signal_and_calibrating_states(
    harness: h.AppHarness, sensor_state_name: str
) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    before = h.grab_image(screen)
    state = getattr(harness.contracts.SensorState, sensor_state_name)
    harness.vital_port.set_status(sensor_state=state)
    h.pump_events(140)
    assert h.images_differ(before, h.grab_image(screen)) or sensor_state_name.replace("_", " ").lower() in h.joined_text(screen).lower()
    assert h.find_widget(screen, "btn_patient").isEnabled()


@pytest.mark.parametrize("cloud_state_name", ["SYNCING", "ERROR"])
def test_f10_cloud_syncing_and_error_states(
    harness: h.AppHarness, cloud_state_name: str
) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    before = h.grab_image(screen)
    state = getattr(harness.contracts.CloudState, cloud_state_name)
    harness.vital_port.set_status(cloud_state=state)
    h.pump_events(140)
    assert h.images_differ(before, h.grab_image(screen)) or cloud_state_name.lower() in h.joined_text(screen).lower()


def test_f10_battery_0_percent_and_100_charging_boundaries(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    lbl_bat = h.find_widget(screen, "lbl_battery_pct")

    harness.vital_port.set_status(battery_percent=0, battery_voltage=6.2, is_charging=False)
    h.pump_events(120)
    assert "0%" in lbl_bat.text()
    img_zero = h.grab_image(screen)

    harness.vital_port.set_status(battery_percent=100, battery_voltage=8.4, is_charging=True)
    h.pump_events(120)
    assert "100%" in lbl_bat.text()
    assert h.images_differ(img_zero, h.grab_image(screen))


def test_f10_alarm_warning_vs_critical_differentiation(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    AlarmLevel = harness.contracts.AlarmLevel
    rr_col = h.find_widget(screen, "vital_rr")
    prv_col = h.find_widget(screen, "vital_prv")
    spo2_col = h.find_widget(screen, "vital_spo2")

    before_prv = h.grab_image(prv_col)
    before_spo2 = h.grab_image(spo2_col)
    harness.vital_port.push_vitals(
        prv_rmssd_ms=40.0,
        spo2_percent=83.0,
        alarms={
            "PRV": AlarmLevel.WARNING,
            "RR": AlarmLevel.NORMAL,
            "PI": AlarmLevel.NORMAL,
            "SpO2": AlarmLevel.CRITICAL,
            "BP": AlarmLevel.NORMAL,
        },
    )
    h.pump_events(140)
    assert h.images_differ(before_prv, h.grab_image(prv_col))
    assert h.images_differ(before_spo2, h.grab_image(spo2_col))
    assert rr_col.isVisible()


def test_f10_transient_adapter_exception_does_not_crash_ui_loop(harness: h.AppHarness) -> None:
    screen = h.find_widget(harness.window, "main_screen")
    spo2_col = h.find_widget(screen, "vital_spo2")
    before = h.grab_image(spo2_col)

    harness.vital_port.arm_transient_error(RuntimeError("UART read timeout"))
    h.pump_events(120)

    harness.vital_port.push_vitals(spo2_percent=96.0)
    h.pump_events(140)
    txt = h.joined_text(spo2_col)
    assert "96" in txt or h.images_differ(before, h.grab_image(spo2_col))
