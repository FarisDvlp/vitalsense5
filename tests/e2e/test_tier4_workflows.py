"""Tier 4 Opaque-Box E2E Tests: Real-world clinical kiosk workflows (W01-W05).

Zero top-level imports of ``vitalsense5`` or ``PyQt6``.
"""

from __future__ import annotations

from pathlib import Path

from tests.e2e import conftest as h
from tests.e2e.screenshot_rubric import run_screenshot_rubric


def test_w01_new_patient_intake_via_virtual_keyboard_and_monitoring(make_app: object) -> None:
    ah = make_app(kiosk=False)
    assert ah.window.width() == 1280 and ah.window.height() == 720

    ppg = h.find_widget(ah.window, "ppg_canvas")
    ppg_t0 = h.grab_image(ppg)
    h.pump_events(120)
    assert h.images_differ(ppg_t0, h.grab_image(ppg))

    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    h.click_widget(h.find_widget(ps, "btn_new_patient"))
    dlg = h.find_overlay(ah, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    h.focus_input_field(name_field)
    h.type_via_keyboard(ah, "Budi X", press_done=False)
    kb = h.find_overlay(ah, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    h.tap_keyboard_key(kb, "BACKSPACE")
    h.type_via_keyboard(ah, "Santoso", press_done=False)
    assert h.find_line_edit(name_field).text() == "Budi Santoso"

    for fname, digits in (
        ("input_patient_age", "45"),
        ("input_patient_height", "172"),
        ("input_patient_weight", "68"),
    ):
        h.focus_input_field(h.find_widget(dlg, fname))
        h.type_via_keyboard(ah, digits, press_done=False)

    # Verify non-occlusion while keyboard is open
    kb_now = h.find_overlay(ah, "virtual_keyboard_overlay", require_visible=True)
    assert kb_now is not None
    kb_rect = h.widget_rect_in_window(kb_now, ah.window)
    for cname in (
        "input_patient_name",
        "input_patient_age",
        "input_patient_height",
        "input_patient_weight",
        "btn_patient_save",
    ):
        assert not h.widget_rect_in_window(h.find_widget(dlg, cname), ah.window).intersects(kb_rect)

    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(
        lambda: h.find_overlay(ah, "new_patient_dialog", require_visible=True) is None,
        description="dialog save close",
    )

    cards_txt = " ".join(h.joined_text(c) for c in h.find_patient_cards(ps))
    assert "Budi Santoso" in cards_txt
    assert ah.patient_store.get_active_patient().name == "Budi Santoso"

    h.click_widget(h.find_widget(ps, "btn_back"))
    ms = h.find_widget(ah.window, "main_screen")
    assert ms.isVisible()
    assert "Budi Santoso" in h.find_widget(ms, "lbl_active_patient").text()

    ppg_t1 = h.grab_image(ppg)
    h.pump_events(120)
    assert h.images_differ(ppg_t1, h.grab_image(ppg))


def test_w02_live_icu_monitoring_settings_and_snapshot_record_session(harness: h.AppHarness) -> None:
    ppg = h.find_widget(harness.window, "ppg_canvas")
    frame1 = h.grab_image(ppg)
    h.pump_events(130)
    frame2 = h.grab_image(ppg)
    assert h.images_differ(frame1, frame2)

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None
    h.click_widget(h.find_settings_row_control(h.find_widget(modal, "settings_row_1")))
    h.click_widget(h.find_settings_row_control(h.find_widget(modal, "settings_row_2")))

    row3 = h.find_widget(modal, "settings_row_3")
    h.click_widget(h.find_settings_row_control(row3))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    for _ in range(5):
        h.tap_keyboard_key(kb, "BACKSPACE")
    h.type_via_keyboard(harness, "150", press_done=True)

    h.select_settings_dropdown(harness, h.find_widget(modal, "settings_row_4"), "Option B")
    h.click_widget(h.find_widget(modal, "btn_settings_close"))

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal_reopen = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert "ON" in h.joined_text(h.find_widget(modal_reopen, "settings_row_1")).upper()
    assert "OFF" in h.joined_text(h.find_widget(modal_reopen, "settings_row_2")).upper()
    assert "150" in h.joined_text(h.find_widget(modal_reopen, "settings_row_3"))
    assert "Option B" in h.joined_text(h.find_widget(modal_reopen, "settings_row_4"))
    h.click_widget(h.find_widget(modal_reopen, "btn_settings_close"))

    btn_rec = h.find_widget(harness.window, "btn_record")
    h.click_widget(btn_rec)
    harness.vital_port.set_status(recording_active=True, recording_elapsed_s=4)
    h.pump_events(150)
    assert btn_rec.text() == "RECORDING..."
    assert h.find_widget(harness.window, "lbl_recording_timer").isVisible()
    h.click_widget(btn_rec)
    assert [c[0] for c in harness.command_handler.record_calls] == [True, False]
    assert btn_rec.text() == "RECORD"
    assert not h.find_widget(harness.window, "lbl_recording_timer").isVisible()


def test_w03_large_ward_drag_scroll_selection_and_edit_roundtrip(make_app: object) -> None:
    ah = make_app(patient_count=18)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)
    assert len(cards) == 18

    h.scroll_into_view_via_drag(scroll, cards[13], max_drags=20)
    assert scroll.verticalScrollBar().value() > 0
    assert h.find_overlay(ah, "new_patient_dialog", require_visible=True) is None

    h.click_widget(cards[13])
    assert ah.patient_store.get_active_patient().name == "Patient Number 14"

    h.click_widget(h.find_widget(ps, "btn_edit_patient"))
    dlg = h.find_overlay(ah, "new_patient_dialog", require_visible=True)
    assert dlg is not None
    assert h.find_line_edit(h.find_widget(dlg, "input_patient_name")).text() == "Patient Number 14"

    wt_field = h.find_widget(dlg, "input_patient_weight")
    h.clear_input_via_keyboard(ah, wt_field)
    h.type_via_keyboard(ah, "75", press_done=True)
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(lambda: len(ah.patient_store.update_calls) == 1, description="edit roundtrip save")

    updated_cards_txt = " ".join(h.joined_text(c) for c in h.find_patient_cards(ps))
    assert "75" in updated_cards_txt

    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "Patient Number 14" in h.find_widget(ah.window, "lbl_active_patient").text()


def test_w04_hardware_fault_and_recovery_lifecycle(harness: h.AppHarness) -> None:
    c = harness.contracts
    ms = h.find_widget(harness.window, "main_screen")
    lbl_uart = h.find_widget(ms, "lbl_uart_status")
    lbl_bat = h.find_widget(ms, "lbl_battery_pct")
    ppg = h.find_widget(ms, "ppg_canvas")

    # Step 1: Finger-off
    before_fo = h.grab_image(ms)
    harness.vital_port.set_status(sensor_state=c.SensorState.FINGER_OFF)
    h.pump_events(140)
    assert h.images_differ(before_fo, h.grab_image(ms)) or "finger" in h.joined_text(ms).lower()

    # Step 2: UART Disconnect
    harness.vital_port.set_status(
        uart_state=c.ConnectionState.DISCONNECTED,
        esp32_state=c.ConnectionState.DISCONNECTED,
    )
    harness.vital_port.push_vitals(
        prv_rmssd_ms=None,
        rr_brpm=None,
        pi_percent=None,
        spo2_percent=None,
        bp_sys_mmhg=None,
        bp_dia_mmhg=None,
    )
    h.pump_events(140)
    assert "disconnect" in lbl_uart.text().lower()

    # Step 3: Reconnect + Cloud offline + Low battery + Critical SpO2 alarm
    harness.vital_port.set_status(
        uart_state=c.ConnectionState.CONNECTED,
        esp32_state=c.ConnectionState.CONNECTED,
        sensor_state=c.SensorState.OK,
        cloud_state=c.CloudState.OFFLINE,
        battery_percent=12,
    )
    harness.vital_port.push_vitals(
        prv_rmssd_ms=60.0,
        rr_brpm=17.0,
        pi_percent=2.8,
        spo2_percent=82.0,
        bp_sys_mmhg=124,
        bp_dia_mmhg=82,
        alarms={
            "PRV": c.AlarmLevel.NORMAL,
            "RR": c.AlarmLevel.NORMAL,
            "PI": c.AlarmLevel.NORMAL,
            "SpO2": c.AlarmLevel.CRITICAL,
            "BP": c.AlarmLevel.NORMAL,
        },
    )
    h.pump_events(140)
    assert "12%" in lbl_bat.text()
    assert "connect" in lbl_uart.text().lower() and "disconnect" not in lbl_uart.text().lower()

    # Step 4: Full recovery
    harness.vital_port.set_status(
        cloud_state=c.CloudState.ONLINE,
        battery_percent=90,
        sensor_state=c.SensorState.OK,
    )
    harness.vital_port.push_vitals(
        spo2_percent=98.0,
        alarms={
            "PRV": c.AlarmLevel.NORMAL,
            "RR": c.AlarmLevel.NORMAL,
            "PI": c.AlarmLevel.NORMAL,
            "SpO2": c.AlarmLevel.NORMAL,
            "BP": c.AlarmLevel.NORMAL,
        },
    )
    harness.vital_port.push_waveform([0.0, 0.9, 0.3, -0.5, 0.0] * 8)
    h.pump_events(150)
    assert "90%" in lbl_bat.text()
    assert h.count_color_pixels(h.grab_image(ppg), "#313131", tolerance=24, stride=1) >= 15


def test_w05_full_1280x720_screenshot_rubric_and_kiosk_audit(
    make_app: object, tmp_path: Path
) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtTest import QTest

    for path in (
        h.REPO_ROOT / "README.md",
        h.REPO_ROOT / "docs" / "FRONTEND_PLAN.md",
        h.REPO_ROOT / "docs" / "DESIGN_GAP_REPORT.md",
    ):
        assert path.is_file() and path.stat().st_size > 500

    report = run_screenshot_rubric(output_dir=tmp_path)
    assert report.passed, report.summary()
    assert len(report.results) == 5
    for res in report.results:
        assert res.image_path.is_file()
        assert res.width == 1280 and res.height == 720
    assert "JetBrains Mono" in set(QFontDatabase.families())

    ah = make_app(kiosk=True)
    assert ah.window.isFullScreen()
    QTest.keyClick(ah.window, Qt.Key.Key_F11)
    h.pump_events(60)
    assert not ah.window.isFullScreen()
    assert ah.window.width() == 1280 and ah.window.height() == 720
