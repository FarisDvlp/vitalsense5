"""Tier 3 Opaque-Box E2E Tests: Pairwise cross-feature interaction tests (C01-C12).

Zero top-level imports of ``vitalsense5`` or ``PyQt6``.
"""

from __future__ import annotations

from tests.e2e import conftest as h


def test_c01_patient_switch_while_recording_active(make_app: object) -> None:
    contracts = h.load_contracts()
    patients = [
        contracts.PatientRecord("p-a", "Patient A", 35, 170, 68),
        contracts.PatientRecord("p-b", "Patient B", 44, 178, 76),
    ]
    ah = make_app(patients=patients, active_patient_id="p-a")

    btn_rec = h.find_widget(ah.window, "btn_record")
    h.click_widget(btn_rec)
    ah.vital_port.set_status(recording_active=True, recording_elapsed_s=2)
    h.pump_events(60)
    assert ah.command_handler.record_calls[0][0] is True
    assert ah.command_handler.record_calls[0][1].patient_id == "p-a"

    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    toast = h.find_widget(ah.window, "toast_banner")
    assert toast.isVisible()
    assert "Cannot change patient while recording" in toast.text()
    h.click_widget(h.find_widget(ps, "btn_back"))

    ms = h.find_widget(ah.window, "main_screen")
    assert ms.isVisible()
    assert "Patient A" in h.find_widget(ms, "lbl_active_patient").text()

    # Recording can still be stopped cleanly afterward, then patient switch succeeds
    if not any(active is False for active, _ in ah.command_handler.record_calls):
        h.click_widget(h.find_widget(ms, "btn_record"))
        h.pump_events(50)
        assert any(active is False for active, _ in ah.command_handler.record_calls)

    h.click_widget(h.find_widget(ms, "btn_patient"))
    h.click_widget(h.find_patient_cards(ps)[1])
    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "Patient B" in h.find_widget(ms, "lbl_active_patient").text()


def test_c02_edit_selected_patient_syncs_main_screen_header(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    h.click_widget(h.find_widget(ps, "btn_edit_patient"))

    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None
    assert h.find_line_edit(h.find_widget(dlg, "input_patient_name")).text() == "Patient Number 2"

    h.clear_input_via_keyboard(harness, h.find_widget(dlg, "input_patient_name"))
    h.type_via_keyboard(harness, "Siti Aminah", press_done=True)
    h.clear_input_via_keyboard(harness, h.find_widget(dlg, "input_patient_age"))
    h.type_via_keyboard(harness, "42", press_done=True)
    h.clear_input_via_keyboard(harness, h.find_widget(dlg, "input_patient_weight"))
    h.type_via_keyboard(harness, "62", press_done=True)

    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.wait_until(lambda: len(harness.patient_store.update_calls) == 1, description="patient edit save")

    cards_text = " ".join(h.joined_text(c) for c in h.find_patient_cards(ps))
    assert "Siti Aminah" in cards_text
    assert "62" in cards_text

    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "Siti Aminah" in h.find_widget(harness.window, "lbl_active_patient").text()
    assert harness.patient_store.get_active_patient().name == "Siti Aminah"


def test_c03_settings_persistence_across_modal_close_and_navigation(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert modal is not None

    h.click_widget(h.find_settings_row_control(h.find_widget(modal, "settings_row_1")))

    row3 = h.find_widget(modal, "settings_row_3")
    h.click_widget(h.find_settings_row_control(row3))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    for _ in range(5):
        h.tap_keyboard_key(kb, "BACKSPACE")
    h.type_via_keyboard(harness, "120", press_done=True)

    h.select_settings_dropdown(harness, h.find_widget(modal, "settings_row_4"), "Option B")
    h.click_widget(h.find_widget(modal, "btn_settings_close"))

    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_back"))
    h.click_widget(h.find_widget(harness.window, "btn_settings"))

    modal2 = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert "ON" in h.joined_text(h.find_widget(modal2, "settings_row_1")).upper()
    assert "120" in h.joined_text(h.find_widget(modal2, "settings_row_3"))
    assert "Option B" in h.joined_text(h.find_widget(modal2, "settings_row_4"))


def test_c04_virtual_keyboard_switches_qwerty_and_numpad_across_fields(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    name_field = h.find_widget(dlg, "input_patient_name")
    age_field = h.find_widget(dlg, "input_patient_age")

    h.focus_input_field(name_field)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and h.keyboard_mode(kb) == "qwerty"
    h.type_via_keyboard(harness, "Ali", press_done=False)

    h.focus_input_field(age_field)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and h.keyboard_mode(kb) == "numpad"
    h.type_via_keyboard(harness, "29", press_done=False)

    h.focus_input_field(name_field)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and h.keyboard_mode(kb) == "qwerty"
    assert h.find_line_edit(name_field).text() == "Ali"
    assert h.find_line_edit(age_field).text() == "29"

    h.click_widget(h.find_widget(dlg, "btn_patient_cancel"))
    h.click_widget(h.find_widget(harness.window, "btn_back"))
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    h.click_widget(h.find_settings_row_control(h.find_widget(modal, "settings_row_3")))
    kb_set = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb_set is not None and h.keyboard_mode(kb_set) == "numpad"


def test_c05_kiosk_toggle_with_modals_and_keyboard_positioning(make_app: object) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    ah = make_app(kiosk=False)
    for toggle in (False, True):
        if toggle:
            QTest.keyClick(ah.window, Qt.Key.Key_F11)
            h.pump_events(80)
            assert ah.window.isFullScreen()

        h.click_widget(h.find_widget(ah.window, "btn_settings"))
        s_modal = h.find_overlay(ah, "settings_modal", require_visible=True)
        assert s_modal is not None
        assert ah.window.rect().contains(h.widget_rect_in_window(s_modal, ah.window))
        h.click_widget(h.find_widget(s_modal, "btn_settings_close"))

        h.click_widget(h.find_widget(ah.window, "btn_patient"))
        h.click_widget(h.find_widget(ah.window, "btn_new_patient"))
        dlg = h.find_overlay(ah, "new_patient_dialog", require_visible=True)
        assert dlg is not None
        h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
        kb = h.find_overlay(ah, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        kb_rect = h.widget_rect_in_window(kb, ah.window)
        for ctrl_name in (
            "input_patient_name",
            "input_patient_age",
            "input_patient_height",
            "input_patient_weight",
            "btn_patient_cancel",
            "btn_patient_save",
        ):
            cr = h.widget_rect_in_window(h.find_widget(dlg, ctrl_name), ah.window)
            assert ah.window.rect().contains(cr)
            assert not cr.intersects(kb_rect)

        h.click_widget(h.find_widget(dlg, "btn_patient_cancel"))
        h.click_widget(h.find_widget(ah.window, "btn_back"))


def test_c06_swappable_custom_adapters_drive_ui_without_mock(make_app: object) -> None:
    contracts = h.load_contracts()
    spy_patients = [contracts.PatientRecord("p-spy", "Dr. Custom Spy", 51, 176, 74)]
    ah = make_app(patients=spy_patients, active_patient_id="p-spy")

    ah.vital_port.push_vitals(
        prv_rmssd_ms=42.0,
        rr_brpm=19.0,
        pi_percent=2.0,
        spo2_percent=94.0,
        bp_sys_mmhg=135,
        bp_dia_mmhg=85,
    )
    ah.vital_port.set_status(battery_percent=67)
    ppg = h.find_widget(ah.window, "ppg_canvas")
    img_a = h.grab_image(ppg)
    ah.vital_port.push_waveform([0.1, 0.9, -0.5, 0.2, 0.8, -0.6] * 5)
    h.pump_events(140)
    img_b = h.grab_image(ppg)

    assert "Dr. Custom Spy" in h.find_widget(ah.window, "lbl_active_patient").text()
    assert "67%" in h.find_widget(ah.window, "lbl_battery_pct").text()
    assert h.images_differ(img_a, img_b)

    h.click_widget(h.find_widget(ah.window, "btn_record"))
    assert len(ah.command_handler.record_calls) == 1

    h.click_widget(h.find_widget(ah.window, "btn_settings"))
    modal = h.find_overlay(ah, "settings_modal", require_visible=True)
    scroll = h.find_widget(modal, "settings_scroll_area")
    row5 = h.find_widget(scroll, "settings_row_5")
    h.scroll_into_view_via_drag(scroll, row5)
    h.click_widget(h.find_settings_row_control(row5))
    assert (5, True) in ah.settings_store.update_calls


def test_c07_drag_scroll_plus_selection_and_edit_large_patient_ward(make_app: object) -> None:
    ah = make_app(patient_count=15)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)

    h.scroll_into_view_via_drag(scroll, cards[11])
    assert scroll.verticalScrollBar().value() > 0
    assert h.find_overlay(ah, "new_patient_dialog", require_visible=True) is None

    h.click_widget(cards[11])
    h.click_widget(h.find_widget(ps, "btn_edit_patient"))
    dlg = h.find_overlay(ah, "new_patient_dialog", require_visible=True)
    assert dlg is not None
    target_rec = ah.patient_store.list_patients()[11]
    assert h.find_line_edit(h.find_widget(dlg, "input_patient_name")).text() == target_rec.name
    assert str(target_rec.age) in h.find_line_edit(h.find_widget(dlg, "input_patient_age")).text()


def test_c08_drag_scroll_and_row_controls_in_settings_modal(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    modal = h.find_overlay(harness, "settings_modal", require_visible=True)
    scroll = h.find_widget(modal, "settings_scroll_area")
    row8 = h.find_widget(scroll, "settings_row_8")

    h.scroll_into_view_via_drag(scroll, row8)
    assert harness.settings_store.update_calls == []

    h.click_widget(h.find_settings_row_control(row8))
    assert (8, True) in harness.settings_store.update_calls

    row3 = h.find_widget(scroll, "settings_row_3")
    h.scroll_into_view_via_drag(scroll, row3)
    h.click_widget(h.find_settings_row_control(row3))
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None
    for _ in range(5):
        h.tap_keyboard_key(kb, "BACKSPACE")
    h.type_via_keyboard(harness, "250", press_done=True)

    slots = {s.slot_index: s.value for s in harness.settings_store.list_settings()}
    assert slots[8] is True
    assert str(slots[3]) == "250"


def test_c09_alarm_threshold_and_fault_recovery_updates_vitals_and_ppg(harness: h.AppHarness) -> None:
    c = harness.contracts
    screen = h.find_widget(harness.window, "main_screen")
    spo2_col = h.find_widget(screen, "vital_spo2")
    ppg = h.find_widget(screen, "ppg_canvas")
    lbl_uart = h.find_widget(screen, "lbl_uart_status")

    normal_img = h.grab_image(spo2_col)
    harness.vital_port.push_vitals(
        spo2_percent=84.0,
        bp_sys_mmhg=185,
        bp_dia_mmhg=115,
        alarms={
            "PRV": c.AlarmLevel.NORMAL,
            "RR": c.AlarmLevel.NORMAL,
            "PI": c.AlarmLevel.NORMAL,
            "SpO2": c.AlarmLevel.CRITICAL,
            "BP": c.AlarmLevel.CRITICAL,
        },
    )
    h.pump_events(140)
    alarm_img = h.grab_image(spo2_col)
    assert h.images_differ(normal_img, alarm_img)

    harness.vital_port.set_status(
        uart_state=c.ConnectionState.DISCONNECTED,
        esp32_state=c.ConnectionState.DISCONNECTED,
        sensor_state=c.SensorState.FINGER_OFF,
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
    disc_spo2_img = h.grab_image(spo2_col)
    assert h.images_differ(alarm_img, disc_spo2_img)

    harness.vital_port.set_status(
        uart_state=c.ConnectionState.CONNECTED,
        esp32_state=c.ConnectionState.CONNECTED,
        sensor_state=c.SensorState.OK,
    )
    harness.vital_port.push_vitals(
        prv_rmssd_ms=70.0,
        rr_brpm=16.0,
        pi_percent=3.1,
        spo2_percent=99.0,
        bp_sys_mmhg=118,
        bp_dia_mmhg=78,
        alarms={
            "PRV": c.AlarmLevel.NORMAL,
            "RR": c.AlarmLevel.NORMAL,
            "PI": c.AlarmLevel.NORMAL,
            "SpO2": c.AlarmLevel.NORMAL,
            "BP": c.AlarmLevel.NORMAL,
        },
    )
    harness.vital_port.push_waveform([0.0, 0.85, 0.2, 0.4, -0.5, 0.0] * 6)
    h.pump_events(140)
    assert "connect" in lbl_uart.text().lower() and "disconnect" not in lbl_uart.text().lower()
    assert "99" in h.joined_text(spo2_col) or h.images_differ(disc_spo2_img, h.grab_image(spo2_col))
    assert h.count_color_pixels(h.grab_image(ppg), "#313131", tolerance=24, stride=1) >= 15


def test_c10_new_patient_validation_error_with_keyboard_and_cancel_cleanup(harness: h.AppHarness) -> None:
    initial_count = len(harness.patient_store.list_patients())
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None

    h.focus_input_field(h.find_widget(dlg, "input_patient_age"))
    h.type_via_keyboard(harness, "999", press_done=True)
    h.click_widget(h.find_widget(dlg, "btn_patient_save"))
    h.pump_events(60)

    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert len(harness.patient_store.list_patients()) == initial_count

    h.click_widget(h.find_widget(dlg, "btn_patient_cancel"))
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is None
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None
    assert len(harness.patient_store.list_patients()) == initial_count


def test_c11_record_session_binds_selected_patient_and_pr_readout(harness: h.AppHarness) -> None:
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    cards = h.find_patient_cards(ps)
    h.click_widget(cards[1])
    h.click_widget(h.find_widget(ps, "btn_back"))

    harness.vital_port.push_vitals(
        prv_rmssd_ms=55.0,
        rr_brpm=18.0,
        pi_percent=4.0,
        spo2_percent=97.0,
        bp_sys_mmhg=118,
        bp_dia_mmhg=76,
        bpm=84,
    )
    h.pump_events(120)

    assert h.find_widget(harness.window, "vital_bp_pr_value").text() == "84"

    btn_rec = h.find_widget(harness.window, "btn_record")
    h.click_widget(btn_rec)
    h.pump_events(60)

    assert len(harness.command_handler.record_calls) == 1
    active, rec_patient = harness.command_handler.record_calls[0]
    assert active is True
    assert rec_patient.patient_id == "p-2"
    assert btn_rec.text() == "RECORDING..."


def test_c12_battery_cloud_and_clock_telemetry_sync_across_screens(harness: h.AppHarness) -> None:
    c = harness.contracts
    harness.vital_port.set_status(battery_percent=15, cloud_state=c.CloudState.OFFLINE)
    h.pump_events(120)
    assert "15%" in h.find_widget(harness.window, "lbl_battery_pct").text()

    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    ps = h.find_widget(harness.window, "patient_screen")
    assert "15%" in h.joined_text(ps)

    harness.vital_port.set_status(battery_percent=88, cloud_state=c.CloudState.ONLINE)
    h.pump_events(120)
    assert "88%" in h.joined_text(ps)

    h.click_widget(h.find_widget(ps, "btn_back"))
    assert "88%" in h.find_widget(harness.window, "lbl_battery_pct").text()
