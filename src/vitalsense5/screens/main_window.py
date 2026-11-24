"""Top-level 1280x720 / Kiosk MainWindow shell, navigation, polling, and overlays."""

from __future__ import annotations

import time
from typing import Literal

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from vitalsense5.contracts import (
    DeviceStatus,
    PatientRecord,
    PatientStorePort,
    SessionCommandPort,
    SettingsPort,
    VitalDataPort,
    VitalSnapshot,
)
from vitalsense5.theme import (
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    jetbrains_mono_font,
    modal_scrim_qss,
)
from vitalsense5.widgets import KeyboardMode, VirtualKeyboardOverlay

from .main_screen import MainScreen
from .new_patient_dialog import NewPatientDialog
from .patient_screen import ConfirmDeleteDialog, PatientScreen
from .settings_modal import SettingsModal


class MainWindow(QMainWindow):
    """Root application window hosting screens, non-blocking modals, keyboard, and polling."""

    def __init__(
        self,
        *,
        vital_port: VitalDataPort,
        patient_store: PatientStorePort,
        settings_store: SettingsPort,
        command_handler: SessionCommandPort,
        kiosk: bool = False,
        tick_ms: int = 33,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("main_window")
        self.setWindowTitle("VitalSense5")

        self._vital_port = vital_port
        self._patient_store = patient_store
        self._settings_store = settings_store
        self._command_handler = command_handler
        self._kiosk = False
        self._tick_ms = max(10, int(tick_ms))

        self._latest_vitals = VitalSnapshot()
        self._last_status = DeviceStatus()
        self._recording_active = False
        self._recording_started_at: float | None = None
        self._active_modal: QWidget | None = None
        self._keyboard_target_meta: dict[QLineEdit, tuple[KeyboardMode, bool, bool]] = {}

        # Central host + 1280x720 stage
        self._central_host = QWidget(self)
        self._central_host.setObjectName("central_host")
        self._central_host.setStyleSheet(
            f"#central_host {{ background-color: {COLORS.SCREEN_BG}; border: none; }}"
        )
        self.setCentralWidget(self._central_host)

        self._root_stage = QWidget(self._central_host)
        self._root_stage.setObjectName("root_stage")
        self._root_stage.setFixedSize(LAYOUT.WINDOW_WIDTH, LAYOUT.WINDOW_HEIGHT)
        self._root_stage.setStyleSheet(
            f"#root_stage {{ background-color: {COLORS.SCREEN_BG}; border: none; }}"
        )

        # Screen stack (MainScreen + PatientScreen)
        self.screen_stack = QStackedWidget(self._root_stage)
        self.screen_stack.setObjectName("screen_stack")
        self.screen_stack.setGeometry(0, 0, LAYOUT.WINDOW_WIDTH, LAYOUT.WINDOW_HEIGHT)
        self.screen_stack.setStyleSheet(
            "#screen_stack { background-color: transparent; border: none; }"
        )

        self.main_screen = MainScreen(self.screen_stack)
        self.patient_screen = PatientScreen(self.screen_stack)
        self.screen_stack.addWidget(self.main_screen)
        self.screen_stack.addWidget(self.patient_screen)
        self.screen_stack.setCurrentWidget(self.main_screen)

        # Non-blocking modal scrim covering host (blocks underlying clicks)
        self.modal_scrim = QFrame(self._central_host)
        self.modal_scrim.setObjectName("modal_scrim")
        self.modal_scrim.setStyleSheet(modal_scrim_qss(selector="#modal_scrim"))
        self.modal_scrim.installEventFilter(self)
        self.modal_scrim.hide()

        # Non-blocking modal cards inside modal_scrim
        self.settings_modal = SettingsModal(
            settings_store=self._settings_store,
            parent=self.modal_scrim,
        )
        self.settings_modal.hide()

        self.new_patient_dialog = NewPatientDialog(
            patient_store=self._patient_store,
            parent=self.modal_scrim,
        )
        self.new_patient_dialog.hide()

        self.confirm_delete_dialog = ConfirmDeleteDialog(parent=self.modal_scrim)
        self.confirm_delete_dialog.hide()

        # Non-blocking toast banner in the 274px gap between SETTINGS and SAVE
        self.toast_banner = QLabel("", self._central_host)
        self.toast_banner.setObjectName("toast_banner")
        self.toast_banner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.toast_banner.setGeometry(515, 630, 254, 46)
        self.toast_banner.setWordWrap(True)
        self.toast_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast_banner.setFont(jetbrains_mono_font(size_px=13, weight=500))
        self.toast_banner.hide()

        # On-screen virtual keyboard overlay docked at bottom of stage above scrim
        self.virtual_keyboard = VirtualKeyboardOverlay(self._central_host)
        self.virtual_keyboard.setGeometry(0, LAYOUT.WINDOW_HEIGHT - 280, LAYOUT.WINDOW_WIDTH, 280)
        self.virtual_keyboard.hide()

        # Timers
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast_banner.hide)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._tick_ms)
        self._poll_timer.timeout.connect(self._on_poll_tick)

        # Wire signals
        self._wire_signals()
        self._register_keyboard_targets()
        self._central_host.installEventFilter(self)

        # Initial data sync
        self._refresh_patient_bindings()
        try:
            self._vital_port.start()
        except Exception:
            pass
        self._on_poll_tick()
        self._poll_timer.start()

        self.set_kiosk_mode(kiosk, show_if_windowed=False)
        self._layout_stage_and_overlays()

    def _wire_signals(self) -> None:
        self.screen_stack.currentChanged.connect(lambda _idx: self._layout_toast_banner())
        self.main_screen.patient_requested.connect(self._show_patient_screen)
        self.main_screen.settings_requested.connect(self.open_settings_modal)
        self.main_screen.record_requested.connect(self._on_record_clicked)

        self.patient_screen.back_requested.connect(self._show_main_screen)
        self.patient_screen.patient_selected.connect(self._on_patient_selected)
        self.patient_screen.delete_patient_requested.connect(self.open_delete_patient_dialog)
        self.patient_screen.new_patient_requested.connect(self.open_new_patient_dialog)
        self.patient_screen.edit_patient_requested.connect(self.open_edit_patient_dialog)

        self.settings_modal.closed.connect(self.close_active_modal)
        self.settings_modal.inputs_rebuilt.connect(self._register_settings_keyboard_targets)

        self.new_patient_dialog.cancelled.connect(self.close_active_modal)
        self.new_patient_dialog.saved.connect(self._on_patient_saved)

        self.confirm_delete_dialog.cancelled.connect(self.close_active_modal)
        self.confirm_delete_dialog.confirmed.connect(self._on_delete_patient_confirmed)

        self.virtual_keyboard.keyboard_shown.connect(self._on_keyboard_shown)
        self.virtual_keyboard.keyboard_hidden.connect(self._on_keyboard_hidden)
        self.virtual_keyboard.done_clicked.connect(self._on_keyboard_hidden)

    def _register_keyboard_targets(self) -> None:
        self._register_line_edit(
            self.new_patient_dialog.input_patient_name,
            mode="qwerty",
            allow_decimal=True,
            allow_mode_switch=True,
        )
        self._register_line_edit(
            self.new_patient_dialog.input_patient_age,
            mode="numpad",
            allow_decimal=False,
            allow_mode_switch=False,
        )
        self._register_line_edit(
            self.new_patient_dialog.input_patient_height,
            mode="numpad",
            allow_decimal=False,
            allow_mode_switch=False,
        )
        self._register_line_edit(
            self.new_patient_dialog.input_patient_weight,
            mode="numpad",
            allow_decimal=False,
            allow_mode_switch=False,
        )
        self._register_settings_keyboard_targets()

    def _prune_deleted_keyboard_targets(self) -> None:
        self._keyboard_target_meta = {
            k: v
            for k, v in self._keyboard_target_meta.items()
            if not sip.isdeleted(k)
        }

    def _on_keyboard_target_destroyed(self, _obj: object = None) -> None:
        self._prune_deleted_keyboard_targets()

    def _register_settings_keyboard_targets(self) -> None:
        patient_edits = set(self.new_patient_dialog.input_fields())
        self._keyboard_target_meta = {
            k: v
            for k, v in self._keyboard_target_meta.items()
            if not sip.isdeleted(k) and k in patient_edits
        }
        for edit in self.settings_modal.get_value_line_edits():
            self._register_line_edit(
                edit,
                mode="numpad",
                allow_decimal=True,
                allow_mode_switch=True,
            )
        self.settings_modal.settings_scroll_area.refresh_touch_targets()

    def _register_line_edit(
        self,
        edit: QLineEdit,
        *,
        mode: KeyboardMode,
        allow_decimal: bool,
        allow_mode_switch: bool,
    ) -> None:
        self._keyboard_target_meta[edit] = (mode, allow_decimal, allow_mode_switch)
        edit.removeEventFilter(self)
        edit.installEventFilter(self)
        try:
            edit.destroyed.disconnect(self._on_keyboard_target_destroyed)
        except (TypeError, RuntimeError):
            pass
        edit.destroyed.connect(self._on_keyboard_target_destroyed)

    @staticmethod
    def _move_cursor_to_end(edit: QLineEdit) -> None:
        if not sip.isdeleted(edit):
            edit.deselect()
            edit.setCursorPosition(len(edit.text()))

    def _reset_keyboard_shift(self) -> None:
        if self.virtual_keyboard.is_shifted():
            for btn in self.virtual_keyboard.findChildren(QPushButton):
                if btn.text() == "SHIFT":
                    btn.click()
                    break

    def _hide_keyboard(self) -> None:
        self._reset_keyboard_shift()
        self.virtual_keyboard.hide_keyboard()

    def _open_keyboard_for(self, edit: QLineEdit) -> None:
        meta = self._keyboard_target_meta.get(edit)
        if meta is None:
            return
        mode, allow_decimal, allow_mode_switch = meta
        self.virtual_keyboard.attach_target(
            edit,
            mode=mode,
            allow_decimal=allow_decimal,
            allow_mode_switch=allow_mode_switch,
        )
        self.virtual_keyboard.raise_()
        if edit in self.settings_modal.get_value_line_edits():
            self.settings_modal.close_dropdown_popover()
            self.settings_modal.settings_scroll_area.ensureWidgetVisible(edit)
        self._move_cursor_to_end(edit)
        QTimer.singleShot(0, lambda e=edit: self._move_cursor_to_end(e))
        self._layout_overlays()

    def _on_keyboard_shown(self, _height: int = 0) -> None:
        self.virtual_keyboard.raise_()
        self._layout_overlays()

    def _on_keyboard_hidden(self) -> None:
        self._reset_keyboard_shift()
        if self.settings_modal.isVisible():
            self.settings_modal.commit_or_revert_all_values()
        self._layout_overlays()

    def set_kiosk_mode(self, kiosk: bool, *, show_if_windowed: bool = True) -> None:
        self._kiosk = bool(kiosk)
        if self._kiosk:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.showFullScreen()
        else:
            if self.windowFlags() & Qt.WindowType.FramelessWindowHint:
                self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            if show_if_windowed or self.isFullScreen() or self.isVisible():
                self.showNormal()
            self.setFixedSize(LAYOUT.WINDOW_WIDTH, LAYOUT.WINDOW_HEIGHT)
        self._layout_stage_and_overlays()

    def _layout_stage_and_overlays(self) -> None:
        if not hasattr(self, "virtual_keyboard"):
            return
        if self._central_host.isVisible() and self._central_host.width() == self.width():
            host_w = self._central_host.width() or self.width() or LAYOUT.WINDOW_WIDTH
            host_h = self._central_host.height() or self.height() or LAYOUT.WINDOW_HEIGHT
        else:
            host_w = self.width() or LAYOUT.WINDOW_WIDTH
            host_h = self.height() or LAYOUT.WINDOW_HEIGHT

        stage_x = max(0, (host_w - LAYOUT.WINDOW_WIDTH) // 2) if host_w >= LAYOUT.WINDOW_WIDTH else 0
        stage_y = max(0, (host_h - LAYOUT.WINDOW_HEIGHT) // 2) if host_h >= LAYOUT.WINDOW_HEIGHT else 0
        self._root_stage.setGeometry(
            stage_x,
            stage_y,
            LAYOUT.WINDOW_WIDTH,
            LAYOUT.WINDOW_HEIGHT,
        )
        self.modal_scrim.setGeometry(0, 0, host_w, host_h)
        self._layout_toast_banner()
        kb_h = self.virtual_keyboard.height()
        self.virtual_keyboard.setGeometry(
            0,
            max(0, host_h - kb_h),
            host_w,
            kb_h,
        )
        self._layout_overlays()

    def _toast_stage_rect(self) -> tuple[int, int, int, int]:
        if hasattr(self, "screen_stack") and self.screen_stack.currentWidget() is self.patient_screen:
            return (296, 630, 254, 46)
        return (515, 630, 254, 46)

    def _layout_toast_banner(self) -> None:
        if not hasattr(self, "toast_banner"):
            return
        if self._central_host.isVisible() and self._central_host.width() == self.width():
            host_w = self._central_host.width() or self.width() or LAYOUT.WINDOW_WIDTH
            host_h = self._central_host.height() or self.height() or LAYOUT.WINDOW_HEIGHT
        else:
            host_w = self.width() or LAYOUT.WINDOW_WIDTH
            host_h = self.height() or LAYOUT.WINDOW_HEIGHT
        stage_x = self._root_stage.x()
        stage_y = self._root_stage.y()
        rel_x, rel_y, toast_w, toast_h = self._toast_stage_rect()
        toast_x = min(stage_x + rel_x, max(8, host_w - toast_w - 8))
        toast_y = min(stage_y + rel_y, max(8, host_h - toast_h - 8))
        self.toast_banner.setGeometry(toast_x, toast_y, toast_w, toast_h)

    def _layout_overlays(self) -> None:
        scrim_w = self.modal_scrim.width() or self.width() or LAYOUT.WINDOW_WIDTH
        scrim_h = self.modal_scrim.height() or self.height() or LAYOUT.WINDOW_HEIGHT
        kb_visible = self.virtual_keyboard.isVisible()
        kb_top_in_scrim = max(0, scrim_h - self.virtual_keyboard.height())

        if self.settings_modal.isVisible():
            w = self.settings_modal.width()
            h = self.settings_modal.height()
            x = max(0, (scrim_w - w) // 2)
            centered_y = max(0, (scrim_h - h) // 2)
            if kb_visible:
                y = max(0, min(centered_y, kb_top_in_scrim - h - 2))
            else:
                y = centered_y
            self.settings_modal.move(x, y)

        if self.new_patient_dialog.isVisible():
            if scrim_w < LAYOUT.NEW_PATIENT_MODAL_WIDTH:
                self.new_patient_dialog.fit_to_width(max(540, scrim_w - 24))
            else:
                self.new_patient_dialog.fit_to_width(LAYOUT.NEW_PATIENT_MODAL_WIDTH)
            w = self.new_patient_dialog.width()
            h = self.new_patient_dialog.height()
            x = max(0, (scrim_w - w) // 2)
            centered_y = max(0, (scrim_h - h) // 2)
            if kb_visible:
                y = max(0, min(centered_y, kb_top_in_scrim - h - 2))
            else:
                y = centered_y
            self.new_patient_dialog.move(x, y)

        if self.confirm_delete_dialog.isVisible():
            w = self.confirm_delete_dialog.width()
            h = self.confirm_delete_dialog.height()
            x = max(0, (scrim_w - w) // 2)
            y = max(0, (scrim_h - h) // 2)
            self.confirm_delete_dialog.move(x, y)

    def open_settings_modal(self) -> None:
        self._hide_keyboard()
        self.new_patient_dialog.hide()
        self.confirm_delete_dialog.hide()
        self.settings_modal.load_settings()
        self._active_modal = self.settings_modal
        self.modal_scrim.show()
        self.modal_scrim.raise_()
        self.settings_modal.show()
        self.settings_modal.raise_()
        self.virtual_keyboard.raise_()
        self._layout_stage_and_overlays()

    def open_new_patient_dialog(self) -> None:
        if self._recording_active:
            self._show_toast("Cannot add patient while recording", level="warning")
            return
        self._hide_keyboard()
        self.settings_modal.hide()
        self.confirm_delete_dialog.hide()
        self.new_patient_dialog.open_create()
        self._active_modal = self.new_patient_dialog
        self.modal_scrim.show()
        self.modal_scrim.raise_()
        self.new_patient_dialog.show()
        self.new_patient_dialog.raise_()
        self.virtual_keyboard.raise_()
        self._layout_stage_and_overlays()

    def open_edit_patient_dialog(self) -> None:
        active = self._safe_get_active_patient()
        if active is None:
            self._show_toast("No active patient selected", level="warning")
            return
        self._hide_keyboard()
        self.settings_modal.hide()
        self.confirm_delete_dialog.hide()
        self.new_patient_dialog.open_edit(active)
        self._active_modal = self.new_patient_dialog
        self.modal_scrim.show()
        self.modal_scrim.raise_()
        self.new_patient_dialog.show()
        self.new_patient_dialog.raise_()
        self.virtual_keyboard.raise_()
        self._layout_stage_and_overlays()

    def open_delete_patient_dialog(self) -> None:
        if self._recording_active:
            self._show_toast("Cannot delete patient while recording", level="warning")
            return
        active = self._safe_get_active_patient()
        if active is None:
            self._show_toast("No active patient selected", level="warning")
            return
        self._hide_keyboard()
        self.settings_modal.hide()
        self.new_patient_dialog.hide()
        self.confirm_delete_dialog.open_for_patient(active)
        self._active_modal = self.confirm_delete_dialog
        self.modal_scrim.show()
        self.modal_scrim.raise_()
        self.confirm_delete_dialog.show()
        self.confirm_delete_dialog.raise_()
        self._layout_stage_and_overlays()

    def close_active_modal(self) -> None:
        self._hide_keyboard()
        self.settings_modal.hide()
        self.new_patient_dialog.hide()
        self.confirm_delete_dialog.hide()
        self.modal_scrim.hide()
        self._active_modal = None

    def _show_main_screen(self) -> None:
        self._refresh_patient_bindings()
        self.screen_stack.setCurrentWidget(self.main_screen)
        self._layout_toast_banner()

    def _show_patient_screen(self) -> None:
        self._refresh_patient_bindings()
        self.screen_stack.setCurrentWidget(self.patient_screen)
        self._layout_toast_banner()

    def _safe_get_active_patient(self) -> PatientRecord | None:
        try:
            return self._patient_store.get_active_patient()
        except Exception:
            return None

    def _refresh_patient_bindings(self) -> None:
        try:
            patients = self._patient_store.list_patients()
        except Exception:
            patients = []
        active = self._safe_get_active_patient()
        active_id = active.patient_id if active is not None else None
        self.main_screen.set_active_patient(active)
        self.patient_screen.set_patients(patients, active_id)

    def _on_patient_selected(self, patient_id: str) -> None:
        if self._recording_active:
            active = self._safe_get_active_patient()
            if active is not None and active.patient_id == patient_id:
                return
            self._show_toast("Cannot change patient while recording", level="warning")
            self.patient_screen.set_selected_patient(
                active.patient_id if active is not None else None
            )
            return

        try:
            record = self._patient_store.set_active_patient(patient_id)
        except Exception as exc:
            self._show_toast(str(exc) or "Failed to select patient", level="error")
            return

        self.main_screen.set_active_patient(record)
        self.patient_screen.set_selected_patient(record.patient_id)

    def _on_delete_patient_confirmed(self, patient_id: str) -> None:
        if self._recording_active:
            self.close_active_modal()
            self._show_toast("Cannot delete patient while recording", level="warning")
            return
        try:
            self._patient_store.delete_patient(patient_id)
        except Exception as exc:
            self.close_active_modal()
            self._show_toast(str(exc) or "Failed to delete patient", level="error")
            return
        self.close_active_modal()
        self._refresh_patient_bindings()
        self._show_toast("Patient deleted", level="info")

    def _on_patient_saved(self, record: PatientRecord) -> None:
        self.close_active_modal()
        self._refresh_patient_bindings()
        self._show_toast(f"Saved {record.name}", level="success")

    def _on_record_clicked(self) -> None:
        next_active = not self._recording_active
        active = self._safe_get_active_patient()
        try:
            ok, msg = self._command_handler.toggle_recording(next_active, active)
        except Exception as exc:
            self._show_toast(f"Record error: {exc}", level="error")
            return

        if ok:
            self._recording_active = next_active
            self._recording_started_at = time.monotonic() if next_active else None
            if hasattr(self._vital_port, "set_recording_state"):
                try:
                    self._vital_port.set_recording_state(next_active)
                except Exception:
                    pass
            self.main_screen.set_recording_active(next_active, 0)

        self._show_toast(
            msg or ("Recording started" if next_active else "Recording stopped"),
            level="info" if ok else "error",
        )

    def _show_toast(
        self,
        message: str,
        *,
        level: Literal["info", "success", "warning", "error"] = "info",
        duration_ms: int = 2400,
    ) -> None:
        if level == "success":
            bg = COLORS.BTN_SUCCESS_BG
            border = COLORS.BATTERY_BORDER
        elif level == "warning":
            bg = COLORS.ALARM_WARNING
            border = COLORS.TEXT_PRIMARY
        elif level == "error":
            bg = COLORS.BTN_DANGER_BG
            border = COLORS.BTN_DANGER_PRESSED_BG
        else:
            bg = COLORS.SURFACE_CARD
            border = COLORS.BRAND_BLUE

        self.toast_banner.setStyleSheet(
            f"#toast_banner {{"
            f" background-color: {bg};"
            f" color: {COLORS.TEXT_PRIMARY};"
            f" border: 2px solid {border};"
            f" border-radius: 10px;"
            f" font-family: '{FONT_FAMILY}';"
            f" padding: 2px 8px;"
            f"}}"
        )
        self._layout_toast_banner()
        self.toast_banner.setText(message)
        self.toast_banner.show()
        self.toast_banner.raise_()
        self._toast_timer.start(duration_ms)

    def _on_poll_tick(self) -> None:
        self.main_screen.refresh_clock()
        self.patient_screen.refresh_clock()

        try:
            status = self._vital_port.device_status()
            self._last_status = status
            self.main_screen.update_device_status(status)
            self.patient_screen.update_device_status(status)
        except Exception:
            status = self._last_status

        try:
            snapshot = self._vital_port.latest_vitals()
            self._latest_vitals = snapshot
            self.main_screen.update_vitals(snapshot, status)
        except Exception:
            pass

        try:
            batch = self._vital_port.pop_waveform_samples()
            self.main_screen.append_waveform(batch)
        except Exception:
            pass

        if self._recording_active:
            if self._recording_started_at is not None:
                elapsed_ms = max(0, int((time.monotonic() - self._recording_started_at) * 1000))
            elif status.recording_active and status.recording_elapsed_s > 0:
                elapsed_ms = int(status.recording_elapsed_s) * 1000
            else:
                elapsed_ms = 0
            self.main_screen.set_recording_active(True, elapsed_ms=elapsed_ms)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if watched is self._central_host and etype == QEvent.Type.Resize:
            self._layout_stage_and_overlays()
            return False

        if isinstance(watched, QLineEdit) and watched in self._keyboard_target_meta:
            if watched.isVisible() and watched.isEnabled():
                if (
                    etype == QEvent.Type.FocusIn
                    or (
                        etype == QEvent.Type.MouseButtonPress
                        and isinstance(event, QMouseEvent)
                        and event.button() == Qt.MouseButton.LeftButton
                    )
                ):
                    self._open_keyboard_for(watched)
                    QTimer.singleShot(0, lambda e=watched: self._move_cursor_to_end(e))
                    return False
                if (
                    etype == QEvent.Type.MouseButtonRelease
                    and isinstance(event, QMouseEvent)
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._move_cursor_to_end(watched)
                    QTimer.singleShot(0, lambda e=watched: self._move_cursor_to_end(e))
                    return False

        if watched is self.modal_scrim and etype == QEvent.Type.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                if self._active_modal is not None and self._active_modal.isVisible():
                    if not self._active_modal.geometry().contains(pos):
                        if self._active_modal is self.settings_modal:
                            self.settings_modal.request_close()
                        elif self._active_modal is self.confirm_delete_dialog:
                            self.close_active_modal()
                        elif self.virtual_keyboard.isVisible():
                            self._hide_keyboard()
                return True

        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F11:
            self.set_kiosk_mode(not self._kiosk)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self.virtual_keyboard.isVisible():
                self._hide_keyboard()
                event.accept()
                return
            if self._active_modal is self.settings_modal and self.settings_modal.isVisible():
                self.settings_modal.request_close()
                event.accept()
                return
            if (
                self._active_modal is self.confirm_delete_dialog
                and self.confirm_delete_dialog.isVisible()
            ):
                self.close_active_modal()
                event.accept()
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_stage_and_overlays()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        self._toast_timer.stop()
        self._hide_keyboard()
        try:
            self._vital_port.stop()
        except Exception:
            pass
        event.accept()


__all__ = ["MainWindow"]
