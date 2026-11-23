"""Unit tests for VitalSense5 M3 widgets and touchscreen input components."""

from __future__ import annotations

import ast
import math
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QEventPoint, QImage, QPointingDevice, QTouchEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vitalsense5.contracts.models import (
    AlarmLevel,
    CloudState,
    ConnectionState,
    DeviceStatus,
    SensorState,
    VitalSnapshot,
    WaveformBatch,
)
from vitalsense5.theme import COLORS, LAYOUT, app_base_qss, load_bundled_fonts
from vitalsense5.widgets import (
    ActionButton,
    BPColumnWidget,
    PPGCanvasWidget,
    StatusHeaderBar,
    TouchScrollArea,
    VirtualKeyboardOverlay,
    VitalColumnWidget,
)

WIDGETS_DIR = Path(__file__).resolve().parents[2] / "src" / "vitalsense5" / "widgets"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    load_bundled_fonts()
    app.setStyleSheet(app_base_qss())
    return app


def _grab(widget: QWidget) -> QImage:
    QApplication.processEvents()
    return widget.grab().toImage()


def _count_color(
    img: QImage,
    hex_color: str,
    *,
    rect: QRect | None = None,
    tolerance: int = 22,
    stride: int = 1,
) -> int:
    target = QColor(hex_color)
    tr, tg, tb = target.red(), target.green(), target.blue()
    bounds = rect if rect is not None else img.rect()
    bounds = bounds.intersected(img.rect())
    tol_sq = tolerance * tolerance
    hits = 0
    for y in range(bounds.top(), bounds.bottom() + 1, stride):
        for x in range(bounds.left(), bounds.right() + 1, stride):
            c = img.pixelColor(x, y)
            dr = c.red() - tr
            dg = c.green() - tg
            db = c.blue() - tb
            if dr * dr + dg * dg + db * db <= tol_sq:
                hits += 1
    return hits


def _images_differ(a: QImage, b: QImage) -> bool:
    if a.size() != b.size():
        return True
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            if a.pixel(x, y) != b.pixel(x, y):
                return True
    return False


def _assert_single_line_labels_not_truncated(root: QWidget) -> None:
    for lbl in root.findChildren(QLabel):
        if not lbl.isVisible():
            continue
        txt = lbl.text().strip()
        if not txt or lbl.wordWrap() or "\n" in txt:
            continue
        adv = lbl.fontMetrics().horizontalAdvance(txt)
        assert adv <= lbl.width() + 8, (
            f"Label {lbl.objectName()!r} text {txt!r} width {adv}px > widget width {lbl.width()}px"
        )


class _ClickableCard(QFrame):
    """Test double simulating a clickable patient card with a child QLabel."""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(71)
        self._pressed = False
        layout = QHBoxLayout(self)
        self.label = QLabel(text, self)
        layout.addWidget(self.label)

    def mousePressEvent(self, event: object) -> None:
        self._pressed = True
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def mouseReleaseEvent(self, event: object) -> None:
        if self._pressed:
            self._pressed = False
            self.clicked.emit()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]


# ===========================================================================
# 1. Exports & Boundary Hygiene
# ===========================================================================


def test_widgets_package_exports_and_no_forbidden_imports() -> None:
    for cls in (
        StatusHeaderBar,
        VitalColumnWidget,
        BPColumnWidget,
        PPGCanvasWidget,
        ActionButton,
        TouchScrollArea,
        VirtualKeyboardOverlay,
    ):
        assert cls is not None

    forbidden = {
        "scipy",
        "numpy",
        "serial",
        "pyserial",
        "sqlite3",
        "sqlalchemy",
        "sklearn",
        "torch",
        "tensorflow",
        "mock_vital_adapter",
    }
    py_files = list(WIDGETS_DIR.glob("*.py"))
    assert len(py_files) == 7
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0].lower())
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0].lower())
                if "adapters" in node.module.lower():
                    mods.add("adapters")
        assert not (mods & (forbidden | {"adapters"})), (
            f"Forbidden imports {mods & (forbidden | {'adapters'})} in {py_file.name}"
        )


# ===========================================================================
# 2. StatusHeaderBar
# ===========================================================================


def test_status_header_bar_logo_labels_and_non_truncation(qapp: QApplication) -> None:
    bar = StatusHeaderBar()
    bar.set_active_patient_name("Patient Number 1")
    bar.refresh_clock(datetime(2026, 10, 16, 10, 30))
    bar.update_device_status(DeviceStatus(battery_percent=100, is_charging=False))
    bar.show()

    img = _grab(bar)
    logo_rect = QRect(20, 15, 115, 110)
    assert _count_color(img, COLORS.BRAND_BLUE, rect=logo_rect, tolerance=22) >= 15
    assert _count_color(img, COLORS.BRAND_CYAN, rect=logo_rect, tolerance=22) >= 15

    assert bar.lbl_active_patient.text() == "Patient Number 1"
    assert "16/10" in bar.lbl_datetime.text()
    assert bar.lbl_battery_pct.text() == "100%"
    assert "connect" in bar.lbl_uart_status.text().lower()
    assert "disconnect" not in bar.lbl_uart_status.text().lower()
    _assert_single_line_labels_not_truncated(bar)

    # Zero overlap with VS5 logo or pairwise among header labels
    vs5_rect = QRect(LAYOUT.LOGO_X, LAYOUT.LOGO_Y, LAYOUT.LOGO_WIDTH, LAYOUT.LOGO_HEIGHT)
    lbls = [bar.lbl_active_patient, bar.lbl_datetime, bar.lbl_uart_status, bar.lbl_battery_pct]
    for i, a in enumerate(lbls):
        assert not a.geometry().intersects(vs5_rect)
        for b in lbls[i + 1 :]:
            inter = a.geometry().intersected(b.geometry())
            assert inter.width() <= 2 or inter.height() <= 2

    bar.close()


def test_status_header_bar_title_mode_uart_cloud_and_battery_states(qapp: QApplication) -> None:
    bar = StatusHeaderBar(show_connection_status=False, title="Patient List")
    bar.show()
    assert bar.lbl_screen_title.isVisible()
    assert bar.lbl_screen_title.text() == "Patient List"
    assert not bar.lbl_active_patient.isVisible()
    assert not bar.lbl_uart_status.isVisible()
    assert bar.lbl_battery_pct.isVisible()

    # Compact badge appears when UART drops on PatientScreen
    bar.update_device_status(DeviceStatus(uart_state=ConnectionState.DISCONNECTED))
    assert not bar.lbl_uart_status.isVisible()
    assert bar.lbl_compact_conn_badge.isVisible()
    assert bar.lbl_compact_conn_badge.text() == "UART Disconnected"

    # Distinguish ESP32-only vs both UART + ESP32 faults
    bar.update_device_status(
        DeviceStatus(uart_state=ConnectionState.CONNECTED, esp32_state=ConnectionState.DISCONNECTED)
    )
    assert bar.lbl_compact_conn_badge.text() == "ESP32 Disconnected"

    bar.update_device_status(
        DeviceStatus(uart_state=ConnectionState.RECONNECTING, esp32_state=ConnectionState.CONNECTED)
    )
    assert bar.lbl_compact_conn_badge.text() == "UART Reconnecting"

    bar.update_device_status(
        DeviceStatus(uart_state=ConnectionState.CONNECTED, esp32_state=ConnectionState.RECONNECTING)
    )
    assert bar.lbl_compact_conn_badge.text() == "ESP32 Reconnecting"

    bar.update_device_status(
        DeviceStatus(uart_state=ConnectionState.DISCONNECTED, esp32_state=ConnectionState.DISCONNECTED)
    )
    assert bar.lbl_compact_conn_badge.text() == "UART / ESP32 Disconnected"
    _assert_single_line_labels_not_truncated(bar)

    # MainScreen connection states + Cloud states + Battery levels
    bar.set_title(None)
    bar.set_uart_visible(True)
    bar.update_device_status(DeviceStatus(uart_state=ConnectionState.RECONNECTING))
    assert bar.lbl_uart_status.isVisible()
    assert "reconnect" in bar.lbl_uart_status.text().lower()

    img_online = _grab(bar)
    assert not bar.lbl_cloud_status.isVisible()

    bar.update_device_status(DeviceStatus(cloud_state=CloudState.OFFLINE, battery_percent=15))
    img_offline = _grab(bar)
    assert bar.lbl_cloud_status.isVisible()
    assert "offline" in bar.lbl_cloud_status.text().lower()
    assert _images_differ(img_online, img_offline)
    assert bar.lbl_battery_pct.text() == "15%"

    bar.update_device_status(DeviceStatus(cloud_state=CloudState.ERROR, battery_percent=5, is_charging=True))
    img_crit = _grab(bar)
    assert bar.lbl_battery_pct.text() == "5%"
    assert _images_differ(img_offline, img_crit)
    _assert_single_line_labels_not_truncated(bar)

    bar.close()


# ===========================================================================
# 3. VitalColumnWidget & BPColumnWidget
# ===========================================================================


def test_vital_columns_accents_values_and_pi_letter_spacing(qapp: QApplication) -> None:
    host = QWidget()
    host.resize(1280, 220)

    prv = VitalColumnWidget(
        vital_key="PRV",
        title="PRV",
        unit="ms",
        accent_color=COLORS.ACCENT_PRV,
        object_name="vital_prv",
        sublabel="RMSSD",
        show_bpm=True,
        width_px=178,
        parent=host,
    )
    rr = VitalColumnWidget(
        vital_key="RR",
        title="RR",
        unit="brpm",
        accent_color=COLORS.ACCENT_RR,
        object_name="vital_rr",
        width_px=218,
        parent=host,
    )
    pi = VitalColumnWidget(
        vital_key="PI",
        title="PI",
        unit="%",
        accent_color=COLORS.ACCENT_PI,
        object_name="vital_pi",
        letter_spacing_px=-3.84,
        width_px=170,
        parent=host,
    )
    spo2 = VitalColumnWidget(
        vital_key="SpO2",
        title="SpO2",
        unit="%",
        accent_color=COLORS.ACCENT_SPO2,
        object_name="vital_spo2",
        width_px=184,
        parent=host,
    )
    bp = BPColumnWidget(object_name="vital_bp", parent=host)

    prv.move(80, 10)
    rr.move(266, 10)
    pi.move(496, 10)
    spo2.move(674, 10)
    bp.move(866, 10)
    host.show()

    snap = VitalSnapshot(
        prv_rmssd_ms=68.0,
        rr_brpm=16.0,
        pi_percent=3.0,
        spo2_percent=98.0,
        bp_sys_mmhg=120,
        bp_dia_mmhg=80,
        bpm=72,
    )
    for col in (prv, rr, pi, spo2, bp):
        col.update_from_snapshot(snap, DeviceStatus())

    assert prv.lbl_value.text() == "68"
    assert prv.lbl_bpm is not None and "72" in prv.lbl_bpm.text()
    assert rr.lbl_value.text() == "16"
    assert pi.lbl_value.text() == "03"
    assert pi.lbl_value.font().letterSpacing() == pytest.approx(-3.84, abs=0.05)
    assert spo2.lbl_value.text() == "98"
    assert bp.lbl_sys_value.text() == "120"
    assert bp.lbl_dia_value.text() == "80"

    for col, hex_color in (
        (prv, COLORS.ACCENT_PRV),
        (rr, COLORS.ACCENT_RR),
        (pi, COLORS.ACCENT_PI),
        (spo2, COLORS.ACCENT_SPO2),
        (bp, COLORS.ACCENT_BP),
    ):
        assert _count_color(_grab(col), hex_color, tolerance=20) >= 10

    _assert_single_line_labels_not_truncated(host)

    # Boundary overflow values must remain untruncated & non-overlapping
    extreme = VitalSnapshot(
        prv_rmssd_ms=199.9,
        rr_brpm=60.0,
        pi_percent=19.9,
        spo2_percent=100.0,
        bp_sys_mmhg=250,
        bp_dia_mmhg=150,
        bpm=180,
    )
    for col in (prv, rr, pi, spo2, bp):
        col.update_from_snapshot(extreme, DeviceStatus())
    _assert_single_line_labels_not_truncated(host)

    for col in (prv, rr, pi, spo2):
        assert not col.lbl_value.geometry().intersects(col.lbl_unit.geometry())
    assert not bp.lbl_dia_value.geometry().intersects(bp.lbl_dia_unit.geometry())

    host.close()


def test_vital_column_stale_nan_and_alarm_scoping(qapp: QApplication) -> None:
    col = VitalColumnWidget(
        vital_key="SpO2",
        title="SpO2",
        unit="%",
        accent_color=COLORS.ACCENT_SPO2,
        object_name="vital_spo2",
        width_px=184,
    )
    col.show()

    # Normal -> Warning -> Critical
    col.set_value(98, alarm=AlarmLevel.NORMAL)
    normal_geom = col.geometry()
    img_norm = _grab(col)

    col.set_value(91, alarm=AlarmLevel.WARNING)
    img_warn = _grab(col)
    assert col.geometry() == normal_geom
    assert _images_differ(img_norm, img_warn)
    assert _count_color(img_warn, COLORS.ALARM_WARNING, tolerance=25) >= 15

    col.set_value(84, alarm=AlarmLevel.CRITICAL)
    img_crit = _grab(col)
    assert col.geometry() == normal_geom
    assert _images_differ(img_warn, img_crit)
    assert _count_color(img_crit, COLORS.ALARM_CRITICAL, tolerance=25) >= 15

    # Child header/unit labels remain free of cascaded border stylesheet
    assert "border" not in col.lbl_header.styleSheet().lower()
    assert "border" not in col.lbl_unit.styleSheet().lower()

    # Stale / None / NaN / FINGER_OFF / DISCONNECTED -> "--"
    col.set_value(float("nan"))
    assert col.lbl_value.text() == "--"

    col.update_from_snapshot(
        VitalSnapshot(spo2_percent=97.0, alarms={"SpO2": AlarmLevel.CRITICAL}),
        DeviceStatus(sensor_state=SensorState.FINGER_OFF),
    )
    assert col.lbl_value.text() == "--"

    col.update_from_snapshot(
        VitalSnapshot(spo2_percent=97.0),
        DeviceStatus(uart_state=ConnectionState.DISCONNECTED),
    )
    assert col.lbl_value.text() == "--"

    bp = BPColumnWidget(object_name="vital_bp")
    bp.show()
    bp.set_bp(185, 115, alarm=AlarmLevel.CRITICAL)
    assert bp.lbl_sys_value.text() == "185"
    assert bp.lbl_dia_value.text() == "115"
    assert _count_color(_grab(bp), COLORS.ALARM_CRITICAL, tolerance=25) >= 15
    bp.set_bp(None, None)
    assert bp.lbl_sys_value.text() == "--"
    assert bp.lbl_dia_value.text() == "--"
    bp.close()

    col.close()


# ===========================================================================
# 4. PPGCanvasWidget
# ===========================================================================


def test_ppg_canvas_geometry_colors_clamping_and_ring_buffer(qapp: QApplication) -> None:
    canvas = PPGCanvasWidget(max_samples=250)
    canvas.show()
    assert canvas.objectName() == "ppg_canvas"
    assert canvas.width() == 1124 and canvas.height() == 250

    # Empty batch is safe no-op
    canvas.append_batch(WaveformBatch(samples=[]))
    assert canvas.samples() == []

    # Out-of-range + non-finite samples clamped & filtered
    canvas.append_samples([0.0, 10.0, -10.0, float("nan"), float("inf"), 0.5, -0.5] * 8)
    assert all(math.isfinite(s) and -1.0 <= s <= 1.0 for s in canvas.samples())

    img = _grab(canvas)
    assert _count_color(img, COLORS.PPG_BG, stride=2) >= 200
    assert _count_color(img, COLORS.PPG_BORDER, stride=2) >= 20
    assert _count_color(img, COLORS.PPG_GRID, stride=2) >= 20
    assert _count_color(img, COLORS.PPG_TRACE, stride=1) >= 15

    # Zero trace pixels may leak into outer 5px border
    top_border = QRect(0, 0, canvas.width(), 4)
    bottom_border = QRect(0, canvas.height() - 4, canvas.width(), 4)
    assert _count_color(img, COLORS.PPG_TRACE, rect=top_border, tolerance=16) == 0
    assert _count_color(img, COLORS.PPG_TRACE, rect=bottom_border, tolerance=16) == 0

    # 1000-sample batch keeps buffer bounded
    canvas.append_batch(WaveformBatch(samples=[0.4 * math.sin(i * 0.2) for i in range(1000)]))
    assert len(canvas.samples()) == 250
    canvas.close()


def test_ppg_canvas_fault_overlays_and_recovery(qapp: QApplication) -> None:
    canvas = PPGCanvasWidget()
    canvas.show()
    canvas.append_samples([0.6 * math.sin(i * 0.25) for i in range(80)])
    assert _count_color(_grab(canvas), COLORS.PPG_TRACE, tolerance=20) >= 15

    # FINGER_OFF suppresses trace and shows banner
    canvas.update_device_status(DeviceStatus(sensor_state=SensorState.FINGER_OFF))
    img_fo = _grab(canvas)
    assert canvas.lbl_ppg_overlay.isVisible()
    assert "finger" in canvas.lbl_ppg_overlay.text().lower()
    assert _count_color(img_fo, COLORS.PPG_TRACE, tolerance=16) == 0

    # DISCONNECTED suppresses trace
    canvas.update_device_status(DeviceStatus(uart_state=ConnectionState.DISCONNECTED))
    assert canvas.lbl_ppg_overlay.isVisible()
    assert "disconnect" in canvas.lbl_ppg_overlay.text().lower()
    assert _count_color(_grab(canvas), COLORS.PPG_TRACE, tolerance=16) == 0

    # POOR_SIGNAL & CALIBRATING overlays keep trace visible
    canvas.update_device_status(DeviceStatus(sensor_state=SensorState.POOR_SIGNAL))
    assert canvas.lbl_ppg_overlay.isVisible()
    assert "poor signal" in canvas.lbl_ppg_overlay.text().lower()

    canvas.update_device_status(DeviceStatus(sensor_state=SensorState.CALIBRATING))
    assert canvas.lbl_ppg_overlay.isVisible()
    assert "calibrating" in canvas.lbl_ppg_overlay.text().lower()

    # Recovery to OK + CONNECTED clears overlay and draws trace
    canvas.update_device_status(DeviceStatus())
    assert not canvas.lbl_ppg_overlay.isVisible()
    assert _count_color(_grab(canvas), COLORS.PPG_TRACE, tolerance=20) >= 15

    # First new sample after fault recovery restarts sweep cleanly from left edge
    canvas.append_samples([0.5])
    assert canvas.samples() == [0.5]
    assert canvas.sweep_index == 1

    canvas.close()


def test_ppg_canvas_125hz_10s_icu_sweep_and_gap(qapp: QApplication) -> None:
    canvas = PPGCanvasWidget()
    canvas.show()
    assert canvas.max_samples == 1250
    assert canvas.gap_samples == 31

    # Fill 1 full 10s pass + 400 samples into the second pass (cursor at 400)
    samples = [0.6 * math.sin(i * 0.15) for i in range(1250 + 400)]
    canvas.append_samples(samples)
    assert len(canvas.samples()) == 1250
    assert canvas.sweep_index == 400

    img = _grab(canvas)
    inner_left = 5 + 2
    usable_w = canvas.width() - 10 - 4
    step_x = usable_w / (1250 - 1)

    # Left of cursor [0..399] has trace pixels
    left_rect = QRect(inner_left + 10, 10, int(350 * step_x), canvas.height() - 20)
    assert _count_color(img, COLORS.PPG_TRACE, rect=left_rect, tolerance=20) >= 10

    # 0.25s erase gap [400..430] (strict interior avoiding dot & endpoints) has 0 trace pixels
    gap_x0 = int(round(inner_left + 404 * step_x))
    gap_x1 = int(round(inner_left + 427 * step_x))
    gap_rect = QRect(gap_x0, 10, max(4, gap_x1 - gap_x0), canvas.height() - 20)
    assert _count_color(img, COLORS.PPG_TRACE, rect=gap_rect, tolerance=16) == 0

    # Right of gap [431..1249] still shows previous pass trace
    right_x0 = int(round(inner_left + 440 * step_x))
    right_rect = QRect(right_x0, 10, canvas.width() - right_x0 - 15, canvas.height() - 20)
    assert _count_color(img, COLORS.PPG_TRACE, rect=right_rect, tolerance=20) >= 10

    canvas.close()


# ===========================================================================
# 5. ActionButton
# ===========================================================================


def test_action_button_variants_and_held_pressed_state(qapp: QApplication) -> None:
    btn = ActionButton("PATIENT", variant="default", object_name="btn_patient")
    btn.show()
    assert btn.width() == 212 and btn.height() == 51
    assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert "JetBrains Mono" in btn.font().family()

    assert _count_color(_grab(btn), COLORS.BTN_DEFAULT_BG, tolerance=18) >= 100

    clicks: list[bool] = []
    btn.clicked.connect(lambda: clicks.append(True))

    QTest.mousePress(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.rect().center())
    QApplication.processEvents()
    assert _count_color(_grab(btn), COLORS.BTN_PRESSED_BG, tolerance=20) >= 100

    QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, btn.rect().center())
    QApplication.processEvents()
    assert _count_color(_grab(btn), COLORS.BTN_DEFAULT_BG, tolerance=18) >= 100
    assert len(clicks) == 1

    # Save / Success and Danger / Recording Active variants
    btn_save = ActionButton("SAVE", variant="save", object_name="btn_save")
    btn_save.show()
    assert _count_color(_grab(btn_save), COLORS.BTN_SUCCESS_BG, tolerance=18) >= 100

    btn_rec = ActionButton("RECORD", variant="danger", object_name="btn_record")
    btn_rec.show()
    assert _count_color(_grab(btn_rec), COLORS.BTN_DANGER_BG, tolerance=18) >= 100

    btn_rec.set_recording_active(True, elapsed_s=65)
    assert btn_rec.text() == "REC 01:05"
    assert _count_color(_grab(btn_rec), COLORS.ALARM_CRITICAL, tolerance=20) >= 100

    btn_rec.set_recording_active(False)
    assert btn_rec.text() == "RECORD"
    assert _count_color(_grab(btn_rec), COLORS.BTN_DANGER_BG, tolerance=18) >= 100

    btn.close()
    btn_save.close()
    btn_rec.close()


# ===========================================================================
# 6. TouchScrollArea
# ===========================================================================


def test_touch_scroll_area_tap_vs_drag_on_buttons_and_cards(qapp: QApplication) -> None:
    scroll = TouchScrollArea(scrollbar_variant="patient", drag_threshold_px=8)
    scroll.resize(400, 260)

    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(10)

    btn_clicks: list[int] = []
    card_clicks: list[int] = []
    buttons: list[QPushButton] = []
    cards: list[_ClickableCard] = []

    for idx in range(10):
        btn = QPushButton(f"Row Button {idx}")
        btn.setFixedHeight(50)
        btn.clicked.connect(lambda _=False, i=idx: btn_clicks.append(i))
        vbox.addWidget(btn)
        buttons.append(btn)

        card = _ClickableCard(f"Card {idx}")
        card.clicked.connect(lambda i=idx: card_clicks.append(i))
        vbox.addWidget(card)
        cards.append(card)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()
    assert scroll.verticalScrollBar().maximum() > 0

    # 1. Sub-threshold 4px move on QPushButton acts as tap (no scroll)
    target_btn = buttons[1]
    start = target_btn.rect().center()
    end_4px = QPoint(start.x(), start.y() - 4)
    QTest.mousePress(target_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(target_btn, end_4px)
    QTest.mouseRelease(target_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_4px)
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() == 0
    assert btn_clicks == [1]

    # 2. Sub-threshold 4px move on child QLabel inside _ClickableCard acts as tap
    target_lbl = cards[1].label
    l_start = target_lbl.rect().center()
    l_end = QPoint(l_start.x(), l_start.y() - 4)
    QTest.mousePress(target_lbl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, l_start)
    QTest.mouseMove(target_lbl, l_end)
    QTest.mouseRelease(target_lbl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, l_end)
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() == 0
    assert card_clicks == [1]

    # 3. Above-threshold drag starting on QPushButton scrolls and suppresses click
    btn_clicks.clear()
    QTest.mousePress(target_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for dy in (-6, -14, -30, -50):
        QTest.mouseMove(target_btn, QPoint(start.x(), start.y() + dy))
        QApplication.processEvents()
    QTest.mouseRelease(target_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(start.x(), start.y() - 50))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0
    assert btn_clicks == []

    # 3b. Above-threshold drag starting on QLabel inside _ClickableCard scrolls and suppresses click
    card_clicks.clear()
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    QTest.mousePress(target_lbl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, l_start)
    for dy in (-6, -16, -32):
        QTest.mouseMove(target_lbl, QPoint(l_start.x(), l_start.y() + dy))
        QApplication.processEvents()
    QTest.mouseRelease(target_lbl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(l_start.x(), l_start.y() - 32))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0
    assert card_clicks == []

    # 4. Dynamic ChildAdded widget is automatically drag-filtered
    dyn_clicks: list[bool] = []
    dyn_btn = QPushButton("Dynamic Child")
    dyn_btn.setFixedHeight(50)
    dyn_btn.clicked.connect(lambda: dyn_clicks.append(True))
    vbox.insertWidget(0, dyn_btn)
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()

    d_start = dyn_btn.rect().center()
    QTest.mousePress(dyn_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, d_start)
    QTest.mouseMove(dyn_btn, QPoint(d_start.x(), d_start.y() - 32))
    QTest.mouseRelease(dyn_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(d_start.x(), d_start.y() - 32))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0
    assert dyn_clicks == []

    # 5. Clamping at 0 and maximum()
    QTest.mousePress(scroll.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 40))
    QTest.mouseMove(scroll.viewport(), QPoint(100, 400))
    QTest.mouseRelease(scroll.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 400))
    assert scroll.verticalScrollBar().value() == 0

    QTest.mousePress(scroll.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 220))
    QTest.mouseMove(scroll.viewport(), QPoint(100, -2500))
    QTest.mouseRelease(scroll.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, -2500))
    assert scroll.verticalScrollBar().value() == scroll.verticalScrollBar().maximum()

    # 6. Settings scrollbar variant compiles & attaches cleanly
    settings_scroll = TouchScrollArea(scrollbar_variant="settings")
    assert "13px" in settings_scroll.verticalScrollBar().styleSheet()
    scroll.close()
    settings_scroll.close()


# ===========================================================================
# 7. VirtualKeyboardOverlay
# ===========================================================================


def _find_visible_key(kb: VirtualKeyboardOverlay, label: str) -> QAbstractButton:
    for btn in kb.findChildren(QAbstractButton):
        if btn.isVisible() and btn.text() == label:
            return btn
    raise AssertionError(f"Key {label!r} not found")


def _assert_visible_keys_valid(kb: VirtualKeyboardOverlay) -> None:
    keys = [b for b in kb.findChildren(QAbstractButton) if b.isVisible()]
    assert len(keys) >= 10
    rects: list[tuple[str, QRect]] = []
    for btn in keys:
        assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert btn.width() >= 28 and btn.height() >= 44
        r = QRect(btn.mapTo(kb, QPoint(0, 0)), btn.size())
        assert kb.rect().contains(r), f"Key {btn.text()!r} exceeds keyboard bounds"
        rects.append((btn.text(), r))
    for i, (na, ra) in enumerate(rects):
        for nb, rb in rects[i + 1 :]:
            inter = ra.intersected(rb)
            assert inter.width() <= 1 or inter.height() <= 1, f"Overlap {na} vs {nb}"


def test_virtual_keyboard_qwerty_shift_numpad_and_signals(qapp: QApplication) -> None:
    host = QWidget()
    host.resize(1280, 720)
    edit = QLineEdit(host)
    edit.setGeometry(100, 80, 400, 50)

    kb = VirtualKeyboardOverlay(host)
    kb.setGeometry(0, 440, 1280, 280)
    kb.hide()
    host.show()

    shown_heights: list[int] = []
    hidden_count: list[int] = []
    done_count: list[int] = []
    mode_events: list[str] = []
    kb.keyboard_shown.connect(shown_heights.append)
    kb.keyboard_hidden.connect(lambda: hidden_count.append(1))
    kb.done_clicked.connect(lambda: done_count.append(1))
    kb.mode_changed.connect(mode_events.append)

    kb.attach_target(edit, mode="qwerty")
    QApplication.processEvents()
    assert kb.isVisible()
    assert kb.property("mode") == "qwerty"
    assert shown_heights == [280]
    _assert_visible_keys_valid(kb)

    # Persistent SHIFT toggles letter keycap text "a".."z" <-> "A".."Z"
    assert _find_visible_key(kb, "a").text() == "a"
    QTest.mouseClick(_find_visible_key(kb, "SHIFT"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert _find_visible_key(kb, "A").text() == "A"
    QTest.mouseClick(_find_visible_key(kb, "A"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "SHIFT"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert _find_visible_key(kb, "a").text() == "a"
    QTest.mouseClick(_find_visible_key(kb, "l"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "i"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "SPACE"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "c"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "BACKSPACE"), Qt.MouseButton.LeftButton)
    assert edit.text() == "Ali "

    QTest.mouseClick(_find_visible_key(kb, "CLEAR"), Qt.MouseButton.LeftButton)
    assert edit.text() == ""
    # Backspace on empty input is safe no-op
    QTest.mouseClick(_find_visible_key(kb, "BACKSPACE"), Qt.MouseButton.LeftButton)
    assert edit.text() == ""

    # Switch to numpad via "123"
    QTest.mouseClick(_find_visible_key(kb, "123"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert kb.property("mode") == "numpad"
    assert mode_events == ["numpad"]
    _assert_visible_keys_valid(kb)

    for digit in ("1", "2", "3", "4", "5"):
        QTest.mouseClick(_find_visible_key(kb, digit), Qt.MouseButton.LeftButton)
    assert edit.text() == "12345"

    # Switch back via "ABC"
    QTest.mouseClick(_find_visible_key(kb, "ABC"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert kb.property("mode") == "qwerty"

    # DONE hides keyboard & emits signals
    QTest.mouseClick(_find_visible_key(kb, "DONE"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not kb.isVisible()
    assert hidden_count == [1]
    assert done_count == [1]

    # Locked numpad (no decimal, no mode switch)
    kb.attach_target(edit, mode="numpad", allow_decimal=False, allow_mode_switch=False)
    QApplication.processEvents()
    assert not _find_visible_key(kb, ".").isEnabled()
    assert not _find_visible_key(kb, "ABC").isEnabled()

    host.close()


# ===========================================================================
# 8. Regression Tests (Iteration 2 Fixes)
# ===========================================================================


def _assert_no_pairwise_label_overlap(root: QWidget, context: str) -> None:
    visible_labels = [lbl for lbl in root.findChildren(QLabel) if lbl.isVisible()]
    for i, a in enumerate(visible_labels):
        ra = QRect(a.mapTo(root, QPoint(0, 0)), a.size())
        for b in visible_labels[i + 1 :]:
            rb = QRect(b.mapTo(root, QPoint(0, 0)), b.size())
            inter = ra.intersected(rb)
            assert inter.width() <= 2 or inter.height() <= 2, (
                f"[{context}] QLabel overlap {a.objectName()!r} {ra} vs {b.objectName()!r} {rb} -> {inter.width()}x{inter.height()}"
            )


def _make_touch_device() -> QPointingDevice:
    return QPointingDevice(
        "test_touchscreen",
        101,
        QPointingDevice.DeviceType.TouchScreen,
        QPointingDevice.PointerType.Finger,
        QPointingDevice.Capability.Position,
        10,
        0,
    )


def _send_touch_event(
    target: QWidget,
    event_type: QEvent.Type,
    dev: QPointingDevice,
    points: list[tuple[int, QEventPoint.State, QPointF]],
) -> QTouchEvent:
    ev_points: list[QEventPoint] = []
    for pid, state, global_pos in points:
        local_pos = QPointF(target.mapFromGlobal(global_pos.toPoint()))
        ev_points.append(QEventPoint(pid, state, local_pos, global_pos))
    ev = QTouchEvent(event_type, dev, Qt.KeyboardModifier.NoModifier, ev_points)
    QApplication.sendEvent(target, ev)
    QApplication.processEvents()
    return ev


def test_touch_scroll_area_qtouchevent_drag_tap_multitouch_and_mouse_recovery(qapp: QApplication) -> None:
    scroll = TouchScrollArea(scrollbar_variant="patient", drag_threshold_px=8)
    scroll.resize(400, 260)

    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(10)

    btn_clicks: list[int] = []
    card_clicks: list[int] = []
    buttons: list[QPushButton] = []
    cards: list[_ClickableCard] = []

    for idx in range(10):
        btn = QPushButton(f"Touch Button {idx}")
        btn.setFixedHeight(50)
        btn.clicked.connect(lambda _=False, i=idx: btn_clicks.append(i))
        vbox.addWidget(btn)
        buttons.append(btn)

        card = _ClickableCard(f"Touch Card {idx}")
        card.clicked.connect(lambda i=idx: card_clicks.append(i))
        vbox.addWidget(card)
        cards.append(card)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()
    dev = _make_touch_device()

    # 1. QTouchEvent drag >= 8px on viewport scrolls cleanly
    vp = scroll.viewport()
    vp_start = QPointF(vp.mapToGlobal(QPoint(100, 180)))
    ev_b = _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(0, QEventPoint.State.Pressed, vp_start)])
    assert ev_b.isAccepted()
    _send_touch_event(
        vp,
        QEvent.Type.TouchUpdate,
        dev,
        [(0, QEventPoint.State.Updated, QPointF(vp_start.x(), vp_start.y() - 60))],
    )
    assert scroll.verticalScrollBar().value() > 0
    _send_touch_event(
        vp,
        QEvent.Type.TouchEnd,
        dev,
        [(0, QEventPoint.State.Released, QPointF(vp_start.x(), vp_start.y() - 60))],
    )

    # 2. QTouchEvent drag >= 8px starting on child QPushButton scrolls and suppresses click
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    btn0 = buttons[0]
    btn_g = QPointF(btn0.mapToGlobal(btn0.rect().center()))
    _send_touch_event(btn0, QEvent.Type.TouchBegin, dev, [(1, QEventPoint.State.Pressed, btn_g)])
    _send_touch_event(
        btn0,
        QEvent.Type.TouchUpdate,
        dev,
        [(1, QEventPoint.State.Updated, QPointF(btn_g.x(), btn_g.y() - 55))],
    )
    # Second-finger TouchBegin mid-drag must NOT reset scroll origin
    _send_touch_event(
        btn0,
        QEvent.Type.TouchBegin,
        dev,
        [
            (1, QEventPoint.State.Stationary, QPointF(btn_g.x(), btn_g.y() - 55)),
            (2, QEventPoint.State.Pressed, QPointF(btn_g.x() + 40, btn_g.y())),
        ],
    )
    sb_mid = scroll.verticalScrollBar().value()
    assert sb_mid > 0
    _send_touch_event(
        btn0,
        QEvent.Type.TouchUpdate,
        dev,
        [
            (1, QEventPoint.State.Updated, QPointF(btn_g.x(), btn_g.y() - 95)),
            (2, QEventPoint.State.Stationary, QPointF(btn_g.x() + 40, btn_g.y())),
        ],
    )
    assert scroll.verticalScrollBar().value() > sb_mid
    _send_touch_event(
        btn0,
        QEvent.Type.TouchEnd,
        dev,
        [(1, QEventPoint.State.Released, QPointF(btn_g.x(), btn_g.y() - 95))],
    )
    assert btn_clicks == []

    # 3. QTouchEvent tap (< 8px) activates child QPushButton and clickable QFrame (via inner QLabel)
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    btn_g2 = QPointF(buttons[1].mapToGlobal(buttons[1].rect().center()))
    _send_touch_event(buttons[1], QEvent.Type.TouchBegin, dev, [(3, QEventPoint.State.Pressed, btn_g2)])
    _send_touch_event(
        buttons[1],
        QEvent.Type.TouchUpdate,
        dev,
        [(3, QEventPoint.State.Updated, QPointF(btn_g2.x(), btn_g2.y() - 3))],
    )
    _send_touch_event(
        buttons[1],
        QEvent.Type.TouchEnd,
        dev,
        [(3, QEventPoint.State.Released, QPointF(btn_g2.x(), btn_g2.y() - 3))],
    )
    assert btn_clicks == [1]

    lbl1 = cards[1].label
    lbl_g = QPointF(lbl1.mapToGlobal(lbl1.rect().center()))
    _send_touch_event(lbl1, QEvent.Type.TouchBegin, dev, [(4, QEventPoint.State.Pressed, lbl_g)])
    _send_touch_event(lbl1, QEvent.Type.TouchEnd, dev, [(4, QEventPoint.State.Released, lbl_g)])
    assert card_clicks == [1]

    # 4. Subsequent QTest.mousePress/Move/Release drag works after touch (TouchCancel & incomplete TouchBegin)
    _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(5, QEventPoint.State.Pressed, vp_start)])
    _send_touch_event(vp, QEvent.Type.TouchCancel, dev, [(5, QEventPoint.State.Released, vp_start)])

    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 180))
    QTest.mouseMove(vp, QPoint(100, 110))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 110))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0

    # Even if a prior touch sequence never delivered TouchEnd, real mouse drag still works
    _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(6, QEventPoint.State.Pressed, vp_start)])
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 180))
    QTest.mouseMove(vp, QPoint(100, 110))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 110))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0

    scroll.close()


def test_action_button_drag_cancel_and_variant_change_no_stuck_pressed(qapp: QApplication) -> None:
    scroll = TouchScrollArea(scrollbar_variant="patient", drag_threshold_px=8)
    scroll.resize(300, 200)

    content = QWidget()
    vbox = QVBoxLayout(content)
    ab = ActionButton("RECORD", variant="danger", object_name="btn_drag_test")
    clicks: list[bool] = []
    ab.clicked.connect(lambda: clicks.append(True))
    vbox.addWidget(ab)
    for idx in range(6):
        filler = QPushButton(f"Item {idx}")
        filler.setFixedHeight(50)
        vbox.addWidget(filler)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()

    # Drag starting on ActionButton cancels press cleanly
    center = ab.rect().center()
    QTest.mousePress(ab, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(ab, QPoint(center.x(), center.y() - 35))
    QTest.mouseRelease(ab, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(center.x(), center.y() - 35))
    QApplication.processEvents()

    assert clicks == []
    assert scroll.verticalScrollBar().value() > 0
    assert ab.property("pressed") is False
    assert ab._pressed_visual is False  # noqa: SLF001

    # Changing variant renders normal #D9D9D9 (not stuck #3F3F3F)
    ab.set_variant("default")
    img_idle = _grab(ab)
    assert _count_color(img_idle, COLORS.BTN_DEFAULT_BG, tolerance=18) > 5000
    assert _count_color(img_idle, COLORS.BTN_PRESSED_BG, tolerance=18) < 500

    # Next real mousePress immediately applies #3F3F3F pressed state
    QTest.mousePress(ab, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QApplication.processEvents()
    assert ab.property("pressed") is True
    assert _count_color(_grab(ab), COLORS.BTN_PRESSED_BG, tolerance=20) >= 100
    QTest.mouseRelease(ab, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QApplication.processEvents()
    assert len(clicks) == 1

    scroll.close()


def test_virtual_keyboard_deleted_target_is_safe_noop(qapp: QApplication) -> None:
    host = QWidget()
    host.resize(1280, 720)
    kb = VirtualKeyboardOverlay(host)
    kb.setGeometry(0, 440, 1280, 280)

    dlg = QWidget(host)
    edit = QLineEdit(dlg)
    host.show()

    kb.attach_target(edit, mode="qwerty")
    QApplication.processEvents()
    assert kb.target() is edit

    # Destroy parent dialog & flush DeferredDelete
    dlg.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    assert kb.target() is None

    # Clicking keys after target deletion must not raise RuntimeError
    QTest.mouseClick(_find_visible_key(kb, "a"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "BACKSPACE"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_key(kb, "CLEAR"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    host.close()


def test_internal_qlabel_pairwise_non_overlap_header_and_vital_columns(qapp: QApplication) -> None:
    # 1. StatusHeaderBar in MainScreen mode and PatientScreen mode
    bar = StatusHeaderBar()
    bar.set_active_patient_name("Patient Number 1")
    bar.refresh_clock(datetime(2026, 10, 16, 10, 30))
    bar.update_device_status(DeviceStatus(cloud_state=CloudState.OFFLINE, battery_percent=100))
    bar.show()
    QApplication.processEvents()
    _assert_no_pairwise_label_overlap(bar, "StatusHeaderBar MainScreen")
    _assert_single_line_labels_not_truncated(bar)

    bar.set_title("Patient List")
    bar.set_uart_visible(False)
    bar.update_device_status(
        DeviceStatus(
            uart_state=ConnectionState.DISCONNECTED,
            esp32_state=ConnectionState.DISCONNECTED,
            cloud_state=CloudState.ERROR,
            battery_percent=100,
        )
    )
    QApplication.processEvents()
    _assert_no_pairwise_label_overlap(bar, "StatusHeaderBar PatientScreen")
    _assert_single_line_labels_not_truncated(bar)
    bar.close()

    # 2. All 5 Vital Columns (normal + extreme boundary values)
    prv = VitalColumnWidget(
        vital_key="PRV",
        title="PRV",
        unit="ms",
        accent_color=COLORS.ACCENT_PRV,
        object_name="vital_prv",
        sublabel="RMSSD",
        show_bpm=True,
        width_px=178,
    )
    rr = VitalColumnWidget(
        vital_key="RR",
        title="RR",
        unit="brpm",
        accent_color=COLORS.ACCENT_RR,
        object_name="vital_rr",
        width_px=218,
    )
    pi = VitalColumnWidget(
        vital_key="PI",
        title="PI",
        unit="%",
        accent_color=COLORS.ACCENT_PI,
        object_name="vital_pi",
        letter_spacing_px=-3.84,
        width_px=170,
    )
    spo2 = VitalColumnWidget(
        vital_key="SpO2",
        title="SpO2",
        unit="%",
        accent_color=COLORS.ACCENT_SPO2,
        object_name="vital_spo2",
        width_px=184,
    )
    bp = BPColumnWidget(object_name="vital_bp")

    cols = [prv, rr, pi, spo2, bp]
    for col in cols:
        col.show()

    normal = VitalSnapshot(
        prv_rmssd_ms=68.0,
        rr_brpm=16.0,
        pi_percent=3.0,
        spo2_percent=98.0,
        bp_sys_mmhg=120,
        bp_dia_mmhg=80,
        bpm=72,
    )
    extreme = VitalSnapshot(
        prv_rmssd_ms=199.9,
        rr_brpm=60.0,
        pi_percent=19.9,
        spo2_percent=100.0,
        bp_sys_mmhg=250,
        bp_dia_mmhg=150,
        bpm=180,
    )
    for snap_name, snap in (("normal", normal), ("extreme", extreme)):
        for col in cols:
            col.update_from_snapshot(snap, DeviceStatus())
            QApplication.processEvents()
            _assert_no_pairwise_label_overlap(col, f"{col.objectName()} {snap_name}")
            _assert_single_line_labels_not_truncated(col)
            col.close() if snap_name == "extreme" else None


# ===========================================================================
# 9. Regression Tests (Iteration 3 Fixes)
# ===========================================================================


def test_touch_scroll_area_deleted_pressed_widget_mid_drag_no_crash_or_lockout(
    qapp: QApplication,
) -> None:
    scroll = TouchScrollArea(scrollbar_variant="settings", drag_threshold_px=8)
    scroll.resize(360, 220)

    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(10)

    ephem_touch_btn = QPushButton("Ephemeral Touch Button")
    ephem_touch_btn.setFixedHeight(50)
    vbox.addWidget(ephem_touch_btn)

    ephem_mouse_btn = QPushButton("Ephemeral Mouse Button")
    ephem_mouse_btn.setFixedHeight(50)
    vbox.addWidget(ephem_mouse_btn)

    for idx in range(10):
        btn = QPushButton(f"Persistent Row {idx}")
        btn.setFixedHeight(50)
        vbox.addWidget(btn)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()
    dev = _make_touch_device()
    vp = scroll.viewport()

    # Prime viewport with a benign touch tap so Qt6 delivers subsequent TouchUpdate/TouchEnd to viewport
    vp_pos = QPointF(vp.mapToGlobal(QPoint(120, 180)))
    _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(0, QEventPoint.State.Pressed, vp_pos)])
    _send_touch_event(vp, QEvent.Type.TouchEnd, dev, [(0, QEventPoint.State.Released, vp_pos)])

    # 1. QTouchEvent path: delete pressed widget after TouchBegin, before >=8px TouchUpdate & TouchEnd
    t_start = QPointF(ephem_touch_btn.mapToGlobal(ephem_touch_btn.rect().center()))
    _send_touch_event(
        ephem_touch_btn,
        QEvent.Type.TouchBegin,
        dev,
        [(1, QEventPoint.State.Pressed, t_start)],
    )
    ephem_touch_btn.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    _send_touch_event(
        vp,
        QEvent.Type.TouchUpdate,
        dev,
        [(1, QEventPoint.State.Updated, QPointF(t_start.x(), t_start.y() - 50))],
    )
    _send_touch_event(
        vp,
        QEvent.Type.TouchEnd,
        dev,
        [(1, QEventPoint.State.Released, QPointF(t_start.x(), t_start.y() - 50))],
    )
    assert scroll._active_source is None  # noqa: SLF001
    assert scroll._active_touch_id is None  # noqa: SLF001
    assert scroll._tracking is False  # noqa: SLF001
    assert scroll._dragging is False  # noqa: SLF001
    assert scroll._pressed_widget is None  # noqa: SLF001

    # Subsequent touch drag still scrolls cleanly
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(2, QEventPoint.State.Pressed, vp_pos)])
    _send_touch_event(
        vp,
        QEvent.Type.TouchUpdate,
        dev,
        [(2, QEventPoint.State.Updated, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    _send_touch_event(
        vp,
        QEvent.Type.TouchEnd,
        dev,
        [(2, QEventPoint.State.Released, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    assert scroll.verticalScrollBar().value() > 0

    # 2. Mouse path: delete pressed widget after mousePress, before >=8px mouseMove & mouseRelease
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    m_center = ephem_mouse_btn.rect().center()
    m_global = ephem_mouse_btn.mapToGlobal(m_center)
    QTest.mousePress(
        ephem_mouse_btn,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        m_center,
    )
    ephem_mouse_btn.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    vp_m_end = vp.mapFromGlobal(QPoint(m_global.x(), m_global.y() - 50))
    QTest.mouseMove(vp, vp_m_end)
    QTest.mouseRelease(
        vp,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        vp_m_end,
    )
    QApplication.processEvents()

    assert scroll._active_source is None  # noqa: SLF001
    assert scroll._tracking is False  # noqa: SLF001
    assert scroll._dragging is False  # noqa: SLF001
    assert scroll._pressed_widget is None  # noqa: SLF001

    # Subsequent mouse and touch drags both scroll cleanly
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(120, 180))
    QTest.mouseMove(vp, QPoint(120, 110))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(120, 110))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > 0

    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    _send_touch_event(vp, QEvent.Type.TouchBegin, dev, [(3, QEventPoint.State.Pressed, vp_pos)])
    _send_touch_event(
        vp,
        QEvent.Type.TouchUpdate,
        dev,
        [(3, QEventPoint.State.Updated, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    _send_touch_event(
        vp,
        QEvent.Type.TouchEnd,
        dev,
        [(3, QEventPoint.State.Released, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    assert scroll.verticalScrollBar().value() > 0

    scroll.close()


def test_touch_scroll_area_tap_transfers_click_focus_to_qlineedit(qapp: QApplication) -> None:
    scroll = TouchScrollArea(scrollbar_variant="settings", drag_threshold_px=8)
    scroll.resize(400, 260)

    content = QWidget()
    vbox = QVBoxLayout(content)
    le1 = QLineEdit("111")
    le2 = QLineEdit("222")
    le_disabled = QLineEdit("333")
    le_disabled.setEnabled(False)
    for le in (le1, le2, le_disabled):
        le.setFixedHeight(48)
        vbox.addWidget(le)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()

    le1.setFocus()
    QApplication.processEvents()
    assert le1.hasFocus()
    assert not le2.hasFocus()

    dev = _make_touch_device()
    le2_pos = QPointF(le2.mapToGlobal(le2.rect().center()))
    _send_touch_event(le2, QEvent.Type.TouchBegin, dev, [(0, QEventPoint.State.Pressed, le2_pos)])
    _send_touch_event(
        le2,
        QEvent.Type.TouchUpdate,
        dev,
        [(0, QEventPoint.State.Updated, QPointF(le2_pos.x(), le2_pos.y() - 3))],
    )
    _send_touch_event(
        le2,
        QEvent.Type.TouchEnd,
        dev,
        [(0, QEventPoint.State.Released, QPointF(le2_pos.x(), le2_pos.y() - 3))],
    )
    assert not le1.hasFocus()
    assert le2.hasFocus()

    # Tapping a disabled QLineEdit must not steal focus
    dis_pos = QPointF(le_disabled.mapToGlobal(le_disabled.rect().center()))
    _send_touch_event(
        le_disabled,
        QEvent.Type.TouchBegin,
        dev,
        [(1, QEventPoint.State.Pressed, dis_pos)],
    )
    _send_touch_event(
        le_disabled,
        QEvent.Type.TouchEnd,
        dev,
        [(1, QEventPoint.State.Released, dis_pos)],
    )
    assert le2.hasFocus()
    assert not le_disabled.hasFocus()

    scroll.close()


def test_vital_bp_bpm_and_header_battery_non_finite_guards(qapp: QApplication) -> None:
    from vitalsense5.widgets.header_bar import StatusHeaderBar

    prv = VitalColumnWidget(
        vital_key="PRV",
        title="PRV",
        unit="ms",
        accent_color=COLORS.ACCENT_PRV,
        object_name="vital_prv_nan",
        show_bpm=True,
    )
    bp = BPColumnWidget(object_name="vital_bp_nan")
    bar = StatusHeaderBar()
    prv.show()
    bp.show()
    bar.show()

    prv.set_value(68.0, bpm=72)
    bp.set_bp(120, 80, alarm=AlarmLevel.CRITICAL)
    assert prv.lbl_bpm is not None and prv.lbl_bpm.text() == "HR 72 BPM"
    assert bp.lbl_sys_value.text() == "120" and bp.lbl_dia_value.text() == "80"

    # Non-finite bpm and BP values mask cleanly to "--" without raising
    prv.set_value(65.0, bpm=float("nan"))  # type: ignore[arg-type]
    bp.set_bp(float("nan"), float("inf"))  # type: ignore[arg-type]
    assert prv.lbl_value.text() == "65"
    assert prv.lbl_bpm.text() == "HR -- BPM"
    assert bp.lbl_sys_value.text() == "--" and bp.lbl_dia_value.text() == "--"

    prv.set_value(65.0, bpm=float("inf"))  # type: ignore[arg-type]
    assert prv.lbl_bpm.text() == "HR -- BPM"

    # Non-finite / bool battery_percent never crashes header bar or battery icon
    bar.update_device_status(
        DeviceStatus(battery_percent=float("nan"), cloud_state=CloudState.OFFLINE)  # type: ignore[arg-type]
    )
    assert bar.lbl_battery_pct.text() == "--%"
    assert bar.lbl_cloud_status.isVisible()
    bar.update_device_status(
        DeviceStatus(battery_percent=True)  # type: ignore[arg-type]
    )
    assert bar.lbl_battery_pct.text() == "--%"
    bar.battery_icon.set_battery_state(float("inf"))

    prv.close()
    bp.close()
    bar.close()


def test_touch_scroll_area_touch_cancel_button_property_reset_and_qwerty_decimal_disabled(
    qapp: QApplication,
) -> None:
    scroll = TouchScrollArea(scrollbar_variant="patient", drag_threshold_px=8)
    scroll.resize(360, 220)

    content = QWidget()
    vbox = QVBoxLayout(content)
    prop_btn = QPushButton("Prop Pressed Button")
    prop_btn.setFixedHeight(50)
    prop_btn.setProperty("pressed", True)
    vbox.addWidget(prop_btn)
    for idx in range(6):
        filler = QPushButton(f"Row {idx}")
        filler.setFixedHeight(50)
        vbox.addWidget(filler)

    scroll.setWidget(content)
    scroll.show()
    QApplication.processEvents()

    # Standard QPushButton with property("pressed") == True gets reset on drag
    center = prop_btn.rect().center()
    QTest.mousePress(prop_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(prop_btn, QPoint(center.x(), center.y() - 30))
    QTest.mouseRelease(prop_btn, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(center.x(), center.y() - 30))
    QApplication.processEvents()
    assert prop_btn.property("pressed") is False
    assert scroll.verticalScrollBar().value() > 0

    # TouchCancel after >=8px TouchUpdate cleans up tracking & pressed state cleanly
    scroll.verticalScrollBar().setValue(0)
    prop_btn.setProperty("pressed", True)
    dev = _make_touch_device()
    vp = scroll.viewport()
    btn_g = QPointF(prop_btn.mapToGlobal(prop_btn.rect().center()))
    _send_touch_event(prop_btn, QEvent.Type.TouchBegin, dev, [(10, QEventPoint.State.Pressed, btn_g)])
    _send_touch_event(
        prop_btn,
        QEvent.Type.TouchUpdate,
        dev,
        [(10, QEventPoint.State.Updated, QPointF(btn_g.x(), btn_g.y() - 32))],
    )
    _send_touch_event(
        prop_btn,
        QEvent.Type.TouchCancel,
        dev,
        [(10, QEventPoint.State.Released, QPointF(btn_g.x(), btn_g.y() - 32))],
    )
    assert prop_btn.property("pressed") is False
    assert scroll._active_source is None  # noqa: SLF001
    assert scroll._tracking is False  # noqa: SLF001
    assert scroll._dragging is False  # noqa: SLF001

    scroll.close()

    # VirtualKeyboardOverlay attach_target(..., mode="qwerty", allow_decimal=False)
    host = QWidget()
    host.resize(1280, 720)
    edit = QLineEdit(host)
    kb = VirtualKeyboardOverlay(host)
    kb.setGeometry(0, 440, 1280, 280)
    host.show()
    kb.attach_target(edit, mode="qwerty", allow_decimal=False, allow_mode_switch=True)
    QApplication.processEvents()
    assert kb.property("mode") == "qwerty"
    assert not kb._btn_numpad_decimal.isEnabled()  # noqa: SLF001
    host.close()


def test_touch_scroll_area_touch_recovers_after_mouse_release_outside(
    qapp: QApplication,
) -> None:
    host = QWidget()
    host.resize(500, 340)

    external = QWidget(host)
    external.setGeometry(0, 0, 500, 60)

    scroll = TouchScrollArea(scrollbar_variant="settings", drag_threshold_px=8, parent=host)
    scroll.setGeometry(20, 70, 440, 240)
    assert scroll.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert scroll.viewport().focusPolicy() == Qt.FocusPolicy.NoFocus

    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(10)
    edit = QLineEdit("123")
    edit.setFixedHeight(48)
    vbox.addWidget(edit)
    for idx in range(10):
        btn = QPushButton(f"Item {idx}")
        btn.setFixedHeight(50)
        vbox.addWidget(btn)
    scroll.setWidget(content)

    host.show()
    QApplication.processEvents()
    dev = _make_touch_device()
    vp = scroll.viewport()
    vp_pos = QPointF(vp.mapToGlobal(QPoint(120, 180)))

    # 1. Start a mouse drag on a child QLineEdit, then release outside on external sibling
    QTest.mousePress(
        edit,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        edit.rect().center(),
    )
    QTest.mouseMove(external, external.rect().center())
    QTest.mouseRelease(
        external,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        external.rect().center(),
    )
    QApplication.processEvents()

    # Subsequent QTouchEvent drag must still scroll cleanly
    scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    ev_b = _send_touch_event(
        vp,
        QEvent.Type.TouchBegin,
        dev,
        [(0, QEventPoint.State.Pressed, vp_pos)],
    )
    assert ev_b.isAccepted()
    _send_touch_event(
        vp,
        QEvent.Type.TouchUpdate,
        dev,
        [(0, QEventPoint.State.Updated, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    _send_touch_event(
        vp,
        QEvent.Type.TouchEnd,
        dev,
        [(0, QEventPoint.State.Released, QPointF(vp_pos.x(), vp_pos.y() - 60))],
    )
    assert scroll.verticalScrollBar().value() > 0

    # 2. Hide / WindowDeactivate clears active tracking state cleanly
    QTest.mousePress(
        edit,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        edit.rect().center(),
    )
    QApplication.processEvents()
    assert scroll._active_source == "mouse"  # noqa: SLF001
    scroll.hide()
    QApplication.processEvents()
    assert scroll._active_source is None  # noqa: SLF001
    assert scroll._tracking is False  # noqa: SLF001
    assert scroll._dragging is False  # noqa: SLF001
    assert scroll._pressed_widget is None  # noqa: SLF001

    scroll.show()
    QApplication.processEvents()
    QTest.mousePress(
        edit,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        edit.rect().center(),
    )
    QApplication.processEvents()
    QApplication.sendEvent(scroll, QEvent(QEvent.Type.WindowDeactivate))
    QApplication.processEvents()
    assert scroll._active_source is None  # noqa: SLF001
    assert scroll._tracking is False  # noqa: SLF001

    host.close()


def test_ppg_canvas_malformed_samples_resilience(qapp: QApplication) -> None:
    canvas = PPGCanvasWidget(max_samples=32)
    canvas.show()
    canvas.append_samples([None, "bad", True, False, float("nan"), float("inf"), 0.25, -0.75])  # type: ignore[list-item]
    assert canvas.samples() == [0.25, -0.75]
    canvas.close()


def test_touch_scroll_area_mouse_recovers_on_strict_ancestor_after_outside_release(
    qapp: QApplication,
) -> None:
    host = QWidget()
    host.resize(500, 340)
    external = QWidget(host)
    external.setGeometry(0, 0, 500, 60)

    scroll = TouchScrollArea(scrollbar_variant="settings", drag_threshold_px=8, parent=host)
    scroll.setGeometry(20, 70, 440, 240)
    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(10)

    row = QFrame()
    row.setFixedHeight(50)
    row_layout = QHBoxLayout(row)
    edit = QLineEdit("123")
    row_layout.addWidget(edit)
    vbox.addWidget(row)
    for idx in range(10):
        btn = QPushButton(f"Item {idx}")
        btn.setFixedHeight(50)
        vbox.addWidget(btn)
    scroll.setWidget(content)
    host.show()
    QApplication.processEvents()
    edit.clearFocus()
    QApplication.processEvents()
    assert not edit.hasFocus()

    # 1. Press on QLineEdit, release outside -> click on strict ancestor (row/viewport) must NOT focus edit
    QTest.mousePress(edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, edit.rect().center())
    QTest.mouseRelease(external, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, external.rect().center())
    QApplication.processEvents()
    QTest.mouseClick(scroll.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QApplication.processEvents()
    assert not edit.hasFocus()

    # 2. Drag QLineEdit up, release outside -> mouse drag on viewport continues scrolling forward
    QTest.mousePress(edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, edit.rect().center())
    QTest.mouseMove(edit, QPoint(edit.rect().center().x(), edit.rect().center().y() - 25))
    QTest.mouseRelease(external, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, external.rect().center())
    QApplication.processEvents()
    sb_before = scroll.verticalScrollBar().value()
    assert sb_before > 0

    vp = scroll.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 200))
    QTest.mouseMove(vp, QPoint(20, 130))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 130))
    QApplication.processEvents()
    assert scroll.verticalScrollBar().value() > sb_before
    host.close()
