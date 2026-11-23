"""Tier 5 Adversarial E2E Tests covering white-box edge cases and regression fixes.

Zero top-level imports of ``vitalsense5`` or ``PyQt6``, and zero private widget
attribute accesses.
"""

from __future__ import annotations

import pytest

from tests.e2e import conftest as h


def test_t5_01_nan_inf_bp_bpm_and_battery_do_not_crash_or_freeze_stale_bp(
    make_app: object,
) -> None:
    """BUG-01 + BUG-02: NaN/Inf in bp/bpm/battery mask cleanly without freezing stale BP or status."""
    ah = make_app()
    c = ah.contracts
    ah.vital_port.push_vitals(
        prv_rmssd_ms=70.0,
        rr_brpm=16.0,
        pi_percent=3.0,
        spo2_percent=98.0,
        bp_sys_mmhg=120,
        bp_dia_mmhg=80,
        bpm=72,
    )
    h.pump_events(100)
    bp_widget = h.find_widget(ah.window, "vital_bp")
    assert "120" in h.joined_text(bp_widget) and "80" in h.joined_text(bp_widget)

    # Emit NaN/Inf in BP + bpm + battery while SpO2 updates to 95 and cloud goes OFFLINE
    ah.vital_port.push_vitals(
        prv_rmssd_ms=65.0,
        rr_brpm=15.0,
        pi_percent=2.5,
        spo2_percent=95.0,
        bp_sys_mmhg=float("nan"),
        bp_dia_mmhg=float("inf"),
        bpm=float("nan"),
    )
    ah.vital_port.set_status(
        battery_percent=float("nan"),
        cloud_state=c.CloudState.OFFLINE,
    )
    h.pump_events(120)

    spo2_widget = h.find_widget(ah.window, "vital_spo2")
    lbl_battery = h.find_widget(ah.window, "lbl_battery_pct")
    main_screen = h.find_widget(ah.window, "main_screen")
    assert "95" in h.joined_text(spo2_widget)
    assert "120" not in h.joined_text(bp_widget) and "--" in h.joined_text(bp_widget)
    assert h.find_widget(bp_widget, "vital_bp_pr_value").text() == "--"
    assert "--%" in lbl_battery.text()
    assert "offline" in h.joined_text(main_screen).lower()


def test_t5_02_settings_value_store_rejection_reverts_on_keyboard_done_and_modal_close(
    qapp: object,
) -> None:
    """BUG-03: Rejected VALUE edits revert to last valid store value on keyboard DONE & modal close."""
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLineEdit

    c = h.load_contracts()
    main_mod = h.load_main_module()

    class _RangeRejectingSettingsPort:
        def __init__(self) -> None:
            self._slots = [
                c.SettingSlot(1, "SETTINGS 1", "SETTINGS 1", c.SettingControlType.TOGGLE, False),
                c.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", c.SettingControlType.VALUE, "100"),
            ]

        def list_settings(self) -> list[object]:
            return list(self._slots)

        def update_setting(self, slot_index: int, value: bool | str) -> object:
            if slot_index == 3:
                num = int(str(value))
                if not (10 <= num <= 200):
                    raise ValueError("Out of range 10..200")
            for idx, slot in enumerate(self._slots):
                if slot.slot_index == slot_index:
                    updated = c.SettingSlot(
                        slot.slot_index,
                        slot.key,
                        slot.label,
                        slot.control_type,
                        str(value) if slot_index == 3 else bool(value),
                        list(slot.options),
                    )
                    self._slots[idx] = updated
                    return updated
            raise KeyError(slot_index)

    store = _RangeRejectingSettingsPort()
    win = main_mod.create_app(settings_store=store, kiosk=False, tick_ms=100)
    win.show()
    h.pump_events(60)
    win_ref = SimpleNamespace(window=win)
    try:
        h.click_widget(h.find_widget(win, "btn_settings"))
        sm = h.find_overlay(win_ref, "settings_modal", require_visible=True)
        assert sm is not None
        val3 = sm.findChild(QLineEdit, "settings_value_3")
        assert val3 is not None

        # Multi-keystroke "1" (rejected intermediate) -> "12" (accepted) -> "120" (accepted)
        h.focus_input_field(val3)
        kb = h.find_overlay(win_ref, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        for _ in range(5):
            h.tap_keyboard_key(kb, "BACKSPACE")
        for ch in "120":
            h.tap_keyboard_key(kb, ch)
        h.tap_keyboard_key(kb, "DONE")
        assert val3.text() == "120"
        assert store.list_settings()[1].value == "120"

        # Rejected "999" + keyboard DONE -> reverts UI to "120"
        h.focus_input_field(val3)
        kb = h.find_overlay(win_ref, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        for _ in range(5):
            h.tap_keyboard_key(kb, "BACKSPACE")
        for ch in "999":
            h.tap_keyboard_key(kb, ch)
        h.tap_keyboard_key(kb, "DONE")
        assert val3.text() == "120"
        assert store.list_settings()[1].value == "120"

        # Rejected "999" + Settings DONE (btn_settings_close) -> reverts & keeps "120"
        h.focus_input_field(val3)
        kb = h.find_overlay(win_ref, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        for _ in range(5):
            h.tap_keyboard_key(kb, "BACKSPACE")
        for ch in "999":
            h.tap_keyboard_key(kb, ch)
        h.click_widget(h.find_widget(sm, "btn_settings_close"))
        assert val3.text() == "120"
        assert store.list_settings()[1].value == "120"
    finally:
        win.close()


def test_t5_03_settings_two_option_dropdown_no_scrollbar_and_long_text_elision(
    make_app: object,
) -> None:
    """BUG-05 + BUG-07: 2/3-option dropdowns have 0 scrollbar overflow; long option text elides cleanly."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QPushButton, QScrollArea, QWidget

    c = h.load_contracts()
    long_a = "Very Long Clinical Mode Option Alpha"
    long_b = "Very Long Clinical Mode Option Beta"
    slots = [
        c.SettingSlot(1, "SETTINGS 1", "SETTINGS 1", c.SettingControlType.DROPDOWN, "Yes", options=["Yes", "No"]),
        c.SettingSlot(2, "SETTINGS 2", "SETTINGS 2", c.SettingControlType.DROPDOWN, long_a, options=[long_a, long_b]),
        c.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", c.SettingControlType.DROPDOWN, "One", options=["One", "Two", "Three"]),
        c.SettingSlot(4, "SETTINGS 4", "SETTINGS 4", c.SettingControlType.TOGGLE, False),
        c.SettingSlot(5, "SETTINGS 5", "SETTINGS 5", c.SettingControlType.TOGGLE, False),
        c.SettingSlot(6, "SETTINGS 6", "SETTINGS 6", c.SettingControlType.TOGGLE, False),
        c.SettingSlot(7, "SETTINGS 7", "SETTINGS 7", c.SettingControlType.TOGGLE, False),
        c.SettingSlot(8, "SETTINGS 8", "SETTINGS 8", c.SettingControlType.TOGGLE, False),
    ]
    ah = make_app(settings=slots)
    h.click_widget(h.find_widget(ah.window, "btn_settings"))
    sm = h.find_overlay(ah, "settings_modal", require_visible=True)
    assert sm is not None

    # 1. 2-option dropdown opens below slot 1 with 0 scrollbar overflow, and re-click toggles closed
    dd1 = h.find_widget(sm, "settings_dropdown_1")
    h.click_widget(dd1)
    popover = sm.findChild(QWidget, "settings_dropdown_popover")
    pop_scroll = sm.findChild(QScrollArea, "settings_dropdown_scroll")
    assert popover is not None and popover.isVisible()
    assert pop_scroll is not None
    assert pop_scroll.verticalScrollBar().maximum() == 0
    assert dd1.mapTo(sm, dd1.rect().bottomLeft()).y() <= popover.y() + 2
    h.click_widget(dd1)
    assert not popover.isVisible()

    # 2. 3-option dropdown also has 0 scrollbar overflow
    dd3 = h.find_widget(sm, "settings_dropdown_3")
    h.click_widget(dd3)
    assert pop_scroll.verticalScrollBar().maximum() == 0

    # 3. Long dropdown button & popover options do not clip horizontally, and direct switch clears old options
    dd2 = h.find_widget(sm, "settings_dropdown_2")
    assert dd2.fontMetrics().horizontalAdvance(dd2.text()) <= dd2.width() - 16
    h.click_widget(dd2)
    assert sm.findChild(QPushButton, "settings_dropdown_opt_3_0") is None
    opt2_0 = sm.findChild(QPushButton, "settings_dropdown_opt_2_0")
    opt2_1 = sm.findChild(QPushButton, "settings_dropdown_opt_2_1")
    assert opt2_0 is not None and opt2_1 is not None
    assert "#DCEAF6" in opt2_0.styleSheet()
    assert opt2_0.width() <= pop_scroll.viewport().width() + 2
    h.click_widget(opt2_1)
    assert ah.settings_store.list_settings()[1].value == long_b


def test_t5_04_mouse_drag_on_settings_value_scrolls_without_opening_keyboard(
    harness: h.AppHarness,
) -> None:
    """BUG-04: Dragging >= 8px starting on settings_value_3 scrolls without opening virtual keyboard."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLineEdit

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    sm = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert sm is not None
    scroll = h.find_widget(sm, "settings_scroll_area")
    val3 = sm.findChild(QLineEdit, "settings_value_3")
    assert val3 is not None

    start = val3.rect().center()
    QTest.mousePress(val3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    h.pump_events(10)
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None

    for dy in (-6, -18, -40):
        QTest.mouseMove(val3, QPoint(start.x(), start.y() + dy))
        h.pump_events(10)
    QTest.mouseRelease(
        val3,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(start.x(), start.y() - 40),
    )
    h.pump_events(50)

    assert scroll.verticalScrollBar().value() > 0
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None

    # Subsequent tap (< 8px) on settings_value_3 still opens numpad keyboard cleanly
    h.scroll_into_view_via_drag(scroll, val3)
    h.focus_input_field(val3)
    kb = h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and h.keyboard_mode(kb) == "numpad"


def test_t5_06_escape_key_and_scrim_dismiss_hierarchy(harness: h.AppHarness) -> None:
    """Escape key dismisses keyboard first then SettingsModal; scrim dismisses keyboard over NewPatientDialog."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLineEdit

    # Settings + Keyboard: 1st Escape hides keyboard, 2nd Escape closes Settings
    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    sm = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert sm is not None
    h.focus_input_field(sm.findChild(QLineEdit, "settings_value_3"))
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is not None

    QTest.keyClick(harness.window, Qt.Key.Key_Escape)
    h.pump_events(40)
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None
    assert h.find_overlay(harness, "settings_modal", require_visible=True) is not None

    QTest.keyClick(harness.window, Qt.Key.Key_Escape)
    h.pump_events(40)
    assert h.find_overlay(harness, "settings_modal", require_visible=True) is None

    # NewPatientDialog + Keyboard: scrim click hides keyboard without discarding dialog
    h.click_widget(h.find_widget(harness.window, "btn_patient"))
    h.click_widget(h.find_widget(harness.window, "btn_new_patient"))
    dlg = h.find_overlay(harness, "new_patient_dialog", require_visible=True)
    assert dlg is not None
    h.focus_input_field(h.find_widget(dlg, "input_patient_name"))
    h.type_via_keyboard(harness, "Ana", press_done=False)
    scrim = h.find_widget(harness.window, "modal_scrim")
    QTest.mouseClick(scrim, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    h.pump_events(40)
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None
    assert h.find_overlay(harness, "new_patient_dialog", require_visible=True) is not None
    assert h.find_line_edit(h.find_widget(dlg, "input_patient_name")).text() == "Ana"


def test_t5_07_adapter_exceptions_and_mock_recording_hook_resilience(qapp: object) -> None:
    """MainWindow exception guards across all 4 ports + NewPatientDialog store failure + MockVitalDataAdapter hook."""
    from types import SimpleNamespace

    h.ensure_src_on_path()
    from vitalsense5.adapters import MockVitalDataAdapter

    main_mod = h.load_main_module()

    class _ExplodingPorts:
        def start(self) -> None:
            raise RuntimeError("start boom")

        def stop(self) -> None:
            raise RuntimeError("stop boom")

        def latest_vitals(self) -> object:
            raise RuntimeError("vitals boom")

        def pop_waveform_samples(self) -> object:
            raise RuntimeError("wave boom")

        def device_status(self) -> object:
            raise RuntimeError("status boom")

        def list_patients(self) -> list[object]:
            raise RuntimeError("list boom")

        def get_active_patient(self) -> object:
            raise RuntimeError("active boom")

        def set_active_patient(self, pid: str) -> object:
            raise KeyError(pid)

        def create_patient(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("save boom")

        def update_patient(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("update boom")

        def delete_patient(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("delete boom")

        def save_snapshot(self, *args: object) -> tuple[bool, str]:
            raise RuntimeError("snapshot boom")

        def toggle_recording(self, *args: object) -> tuple[bool, str]:
            raise RuntimeError("record boom")

    ep = _ExplodingPorts()
    win = main_mod.create_app(vital_port=ep, patient_store=ep, command_handler=ep, kiosk=False, tick_ms=100)
    win.show()
    h.pump_events(60)
    try:
        h.click_widget(h.find_widget(win, "btn_record"))
        assert "Record error" in h.find_widget(win, "toast_banner").text()
        h.click_widget(h.find_widget(win, "btn_patient"))
        h.click_widget(h.find_widget(win, "btn_new_patient"))
        dlg = h.find_overlay(SimpleNamespace(window=win), "new_patient_dialog", require_visible=True)
        assert dlg is not None
        h.find_line_edit(h.find_widget(dlg, "input_patient_name")).setText("Bob")
        h.find_line_edit(h.find_widget(dlg, "input_patient_age")).setText("12.5")
        h.find_line_edit(h.find_widget(dlg, "input_patient_height")).setText("170")
        h.find_line_edit(h.find_widget(dlg, "input_patient_weight")).setText("65")
        h.click_widget(h.find_widget(dlg, "btn_patient_save"))
        assert h.find_widget(dlg, "lbl_patient_error").isVisible()
        h.find_line_edit(h.find_widget(dlg, "input_patient_age")).setText("30")
        h.click_widget(h.find_widget(dlg, "btn_patient_save"))
        assert "save boom" in h.find_widget(dlg, "lbl_patient_error").text()
    finally:
        win.close()

    # Verify MockVitalDataAdapter.set_recording_state integration from UI click
    mock_vp = MockVitalDataAdapter()
    win2 = main_mod.create_app(vital_port=mock_vp, kiosk=False, tick_ms=50)
    win2.show()
    h.pump_events(40)
    try:
        h.click_widget(h.find_widget(win2, "btn_record"))
        assert mock_vp.device_status().recording_active is True
        h.click_widget(h.find_widget(win2, "btn_record"))
        assert mock_vp.device_status().recording_active is False
    finally:
        win2.close()


def test_t5_08_new_patient_dialog_fit_to_width_shrink_restore_and_ppg_2_sample_clear(
    qapp: object,
) -> None:
    """NewPatientDialog.fit_to_width(<875 -> >=875) + PPGCanvasWidget 2-sample & clear_waveform()."""
    from types import SimpleNamespace

    main_mod = h.load_main_module()
    win = main_mod.create_app(kiosk=False, tick_ms=5000)
    win.show()
    h.pump_events(40)
    try:
        ppg = h.find_widget(win, "ppg_canvas")
        ppg.clear_waveform()
        assert ppg.samples() == []
        ppg.append_samples([0.1, 0.8])
        assert len(ppg.samples()) == 2
        assert h.count_color_pixels(h.grab_image(ppg), "#313131", tolerance=24, stride=1) >= 2
        ppg.clear_waveform()
        assert ppg.samples() == []

        win.setMinimumSize(0, 0)
        win.setMaximumSize(16777215, 16777215)
        win.resize(700, 600)
        h.pump_events(30)
        h.click_widget(h.find_widget(win, "btn_patient"))
        h.click_widget(h.find_widget(win, "btn_new_patient"))
        dlg = h.find_overlay(SimpleNamespace(window=win), "new_patient_dialog", require_visible=True)
        assert dlg is not None
        assert dlg.width() < 875
        win.resize(1280, 720)
        h.pump_events(40)
        assert dlg.width() == 875 and dlg.height() == 231
    finally:
        win.close()


def test_t5_09_patient_card_drag_cancel_does_not_stick_subsequent_tap(
    make_app: object,
) -> None:
    """BUG-04: Cancelling a drag starting on a patient card cleanly resets card press state for later taps."""
    ah = make_app(patient_count=12)
    h.click_widget(h.find_widget(ah.window, "btn_patient"))
    ps = h.find_widget(ah.window, "patient_screen")
    scroll = h.find_widget(ps, "patient_scroll_area")
    cards = h.find_patient_cards(ps)

    card1_center_vp = cards[1].mapTo(scroll.viewport(), cards[1].rect().center())
    ratio_y = card1_center_vp.y() / max(1, scroll.viewport().height())
    h.touch_drag(scroll, dy_px=-80, start_ratio=(0.5, ratio_y))
    assert scroll.verticalScrollBar().value() > 0
    assert ah.patient_store.get_active_patient().patient_id == "p-1"

    # Scroll back to top and verify tapping cards[1] selects p-2 cleanly
    h.touch_drag(scroll, dy_px=120, start_ratio=(0.5, 0.3))
    assert scroll.verticalScrollBar().value() == 0
    h.click_widget(cards[1])
    assert ah.patient_store.get_active_patient().patient_id == "p-2"


def test_t5_10_settings_scrollable_dropdown_drag_and_select_does_not_open_keyboard(
    make_app: object,
) -> None:
    """BUG-08: Scrolling an 8-option dropdown popover and selecting an option must not focus VALUE or open keyboard."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton

    c = h.load_contracts()
    slots = [
        c.SettingSlot(1, "SETTINGS 1", "SETTINGS 1", c.SettingControlType.TOGGLE, False),
        c.SettingSlot(2, "SETTINGS 2", "SETTINGS 2", c.SettingControlType.TOGGLE, True),
        c.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", c.SettingControlType.VALUE, "000"),
        c.SettingSlot(
            4,
            "SETTINGS 4",
            "SETTINGS 4",
            c.SettingControlType.DROPDOWN,
            "Opt 1",
            options=[f"Opt {i}" for i in range(1, 9)],
        ),
    ]
    ah = make_app(settings=slots)
    h.click_widget(h.find_widget(ah.window, "btn_settings"))
    sm = h.find_overlay(ah, "settings_modal", require_visible=True)
    assert sm is not None

    dd4 = h.find_widget(sm, "settings_dropdown_4")
    h.click_widget(dd4)
    opt0 = sm.findChild(QPushButton, "settings_dropdown_opt_4_0")
    assert opt0 is not None
    p0 = opt0.rect().center()
    QTest.mousePress(opt0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for dy in (-10, -40, -90):
        QTest.mouseMove(opt0, QPoint(p0.x(), p0.y() + dy))
        h.pump_events(10)
    QTest.mouseRelease(
        opt0,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(p0.x(), p0.y() - 90),
    )
    h.pump_events(30)

    opt5 = sm.findChild(QPushButton, "settings_dropdown_opt_4_5")
    assert opt5 is not None
    h.click_widget(opt5)
    assert ah.settings_store.list_settings()[3].value == "Opt 6"
    assert h.find_overlay(ah, "virtual_keyboard_overlay", require_visible=True) is None


def test_t5_11_malformed_waveform_batch_and_normalized_settings_value_sync(
    qapp: object,
) -> None:
    """Malformed WaveformBatch entries do not drop valid samples; normalized VALUE store responses sync UI."""
    from datetime import datetime
    from types import SimpleNamespace
    from PyQt6.QtWidgets import QLineEdit

    c = h.load_contracts()
    main_mod = h.load_main_module()

    class _NormalizingSettingsPort:
        def __init__(self) -> None:
            self._slots = [
                c.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", c.SettingControlType.VALUE, "50"),
            ]

        def list_settings(self) -> list[object]:
            return list(self._slots)

        def update_setting(self, slot_index: int, value: bool | str) -> object:
            normalized = str(int(str(value).strip()))
            updated = c.SettingSlot(
                slot_index,
                "SETTINGS 3",
                "SETTINGS 3",
                c.SettingControlType.VALUE,
                normalized,
            )
            self._slots[0] = updated
            return updated

    class _MalformedWaveformPort(h.FakeVitalDataPort):
        def __init__(self, contracts_ns: SimpleNamespace) -> None:
            super().__init__(contracts_ns)
            self._emitted_malformed = False

        def pop_waveform_samples(self) -> object:
            if not self._emitted_malformed:
                self._emitted_malformed = True
                return c.WaveformBatch(
                    samples=[None, "bad", True, float("nan"), 0.25, 0.75],
                    sample_rate_hz=125.0,
                    timestamp=datetime.now(),
                )
            return c.WaveformBatch(samples=[], sample_rate_hz=125.0, timestamp=datetime.now())

    vital_port = _MalformedWaveformPort(c)
    settings_store = _NormalizingSettingsPort()
    win = main_mod.create_app(
        vital_port=vital_port,
        settings_store=settings_store,
        kiosk=False,
        tick_ms=40,
    )
    win.show()
    h.pump_events(120)
    win_ref = SimpleNamespace(window=win)
    try:
        ppg = h.find_widget(win, "ppg_canvas")
        assert ppg.samples() == [0.25, 0.75]

        h.click_widget(h.find_widget(win, "btn_settings"))
        sm = h.find_overlay(win_ref, "settings_modal", require_visible=True)
        assert sm is not None
        val3 = sm.findChild(QLineEdit, "settings_value_3")
        assert val3 is not None

        h.focus_input_field(val3)
        kb = h.find_overlay(win_ref, "virtual_keyboard_overlay", require_visible=True)
        assert kb is not None
        for _ in range(4):
            h.tap_keyboard_key(kb, "BACKSPACE")
        for ch in "0075":
            h.tap_keyboard_key(kb, ch)
        h.tap_keyboard_key(kb, "DONE")

        assert settings_store.list_settings()[0].value == "75"
        assert val3.text() == "75"
    finally:
        win.close()


def test_t5_12_settings_mouse_release_outside_does_not_trigger_keyboard_or_break_ancestor_drag(
    harness: h.AppHarness,
) -> None:
    """BUG-10: Outside mouse release from settings_value_3 must not hijack subsequent clicks/drags on row/viewport."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QLineEdit, QWidget

    h.click_widget(h.find_widget(harness.window, "btn_settings"))
    sm = h.find_overlay(harness, "settings_modal", require_visible=True)
    assert sm is not None
    scroll = h.find_widget(sm, "settings_scroll_area")
    vp = scroll.viewport()
    val3 = sm.findChild(QLineEdit, "settings_value_3")
    row3 = sm.findChild(QWidget, "settings_row_3")
    header = sm.findChild(QWidget, "settings_modal_header")
    assert val3 is not None and row3 is not None and header is not None

    # 1. Press on val3, release outside on header without dragging -> click on row3 / Row 1 must NOT open keyboard
    QTest.mousePress(val3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, val3.rect().center())
    QTest.mouseRelease(header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, header.rect().center())
    h.pump_events(20)

    QTest.mouseClick(row3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 24))
    h.pump_events(30)
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None

    QTest.mousePress(val3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, val3.rect().center())
    QTest.mouseRelease(header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, header.rect().center())
    h.pump_events(20)

    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
    h.pump_events(30)
    assert h.find_overlay(harness, "virtual_keyboard_overlay", require_visible=True) is None

    # 2. Drag val3 up -> release outside on header -> subsequent mouse drag on viewport scrolls forward (not backward)
    QTest.mousePress(val3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, val3.rect().center())
    QTest.mouseMove(val3, QPoint(val3.rect().center().x(), val3.rect().center().y() - 25))
    QTest.mouseRelease(header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, header.rect().center())
    h.pump_events(20)

    sb_before = scroll.verticalScrollBar().value()
    assert sb_before > 0
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 200))
    QTest.mouseMove(vp, QPoint(20, 130))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 130))
    h.pump_events(30)
    assert scroll.verticalScrollBar().value() > sb_before
