"""Header status bar widget for VitalSense5 screens."""

from __future__ import annotations

from datetime import datetime
import math

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel, QWidget

from vitalsense5.contracts.models import CloudState, ConnectionState, DeviceStatus
from vitalsense5.theme import COLORS, LAYOUT, TYPOGRAPHY, font_from_token, get_icon_path

_WEEKDAYS_ID: tuple[str, ...] = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")


def _safe_battery_percent(raw_pct: object) -> int | None:
    if raw_pct is None or isinstance(raw_pct, bool):
        return None
    try:
        val = float(raw_pct)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(val):
        return None
    return max(0, min(100, int(round(val))))


class _SvgBadgeWidget(QWidget):
    """Renders a bundled SVG icon with optional solid-color tinting."""

    def __init__(
        self,
        icon_filename: str,
        *,
        object_name: str,
        tint_color: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"#{object_name} {{ background-color: transparent; border: none; }}")
        self._renderer = QSvgRenderer(str(get_icon_path(icon_filename)))
        self._tint_color = tint_color

    def set_tint_color(self, tint_color: str | None) -> None:
        if self._tint_color != tint_color:
            self._tint_color = tint_color
            self.update()

    def paintEvent(self, event: object) -> None:
        if not self._renderer.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        target_rect = QRectF(0, 0, self.width(), self.height())
        if self._tint_color is None:
            self._renderer.render(painter, target_rect)
        else:
            pm = QPixmap(max(1, self.width()), max(1, self.height()))
            pm.fill(Qt.GlobalColor.transparent)
            pm_painter = QPainter(pm)
            pm_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._renderer.render(pm_painter, target_rect)
            pm_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            pm_painter.fillRect(pm.rect(), QColor(self._tint_color))
            pm_painter.end()
            painter.drawPixmap(0, 0, pm)
        painter.end()


class _BatteryIconWidget(QWidget):
    """Dynamic QPainter battery level and charging state indicator."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("battery_icon")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("#battery_icon { background-color: transparent; border: none; }")
        self._battery_percent: int = 95
        self._is_charging: bool = False

    def set_battery_state(self, percent: int | float | None, *, is_charging: bool = False) -> None:
        safe = _safe_battery_percent(percent)
        clamped = 0 if safe is None else safe
        if self._battery_percent != clamped or self._is_charging != bool(is_charging):
            self._battery_percent = clamped
            self._is_charging = bool(is_charging)
            self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._battery_percent <= 10:
            border_color = QColor(COLORS.BATTERY_CRITICAL)
            fill_color = QColor(COLORS.BATTERY_CRITICAL)
        elif self._battery_percent <= 20:
            border_color = QColor(COLORS.BATTERY_LOW)
            fill_color = QColor(COLORS.BATTERY_LOW)
        else:
            border_color = QColor(COLORS.BATTERY_BORDER)
            fill_color = QColor(COLORS.BATTERY_FILL)

        w = float(self.width())
        h = float(self.height())

        # Top terminal nub
        nub_w = w * 0.48
        nub_h = max(3.0, h * 0.10)
        nub_rect = QRectF((w - nub_w) / 2.0, 0.0, nub_w, nub_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(border_color)
        painter.drawRoundedRect(nub_rect, 1.2, 1.2)

        # Outer shell
        shell_top = nub_h - 0.5
        shell_rect = QRectF(1.0, shell_top + 1.0, w - 2.0, h - shell_top - 2.0)
        pen = QPen(border_color, 2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(shell_rect, 2.5, 2.5)

        # Proportional fill inside cavity
        cavity_left = 3.0
        cavity_right = w - 3.0
        cavity_top = shell_top + 3.0
        cavity_bottom = h - 3.0
        cavity_h = max(0.0, cavity_bottom - cavity_top)
        fill_h = cavity_h * (self._battery_percent / 100.0)
        if fill_h > 0.5:
            fill_rect = QRectF(
                cavity_left,
                cavity_bottom - fill_h,
                max(1.0, cavity_right - cavity_left),
                fill_h,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(fill_rect, 1.2, 1.2)

        # Charging lightning bolt
        if self._is_charging:
            cx = w / 2.0
            cy = (cavity_top + cavity_bottom) / 2.0
            bolt = QPolygonF(
                [
                    QPointFCompat(cx + 1.5, cy - 8.0),
                    QPointFCompat(cx - 4.0, cy + 0.5),
                    QPointFCompat(cx - 0.5, cy + 0.5),
                    QPointFCompat(cx - 2.0, cy + 8.0),
                    QPointFCompat(cx + 4.5, cy - 0.5),
                    QPointFCompat(cx + 0.8, cy - 0.5),
                ]
            )
            path = QPainterPath()
            path.addPolygon(bolt)
            path.closeSubpath()
            painter.setPen(QPen(QColor("#FFFFFF"), 1.0))
            painter.setBrush(QColor(COLORS.TEXT_PRIMARY))
            painter.drawPath(path)

        painter.end()


def QPointFCompat(x: float, y: float):  # noqa: N802
    from PyQt6.QtCore import QPointF

    return QPointF(x, y)


class StatusHeaderBar(QWidget):
    """Top 1280x124 status header bar shared across MainScreen and PatientScreen."""

    def __init__(
        self,
        *,
        show_connection_status: bool = True,
        title: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("status_header_bar")
        self.setFixedSize(LAYOUT.WINDOW_WIDTH, 124)
        self.setStyleSheet("#status_header_bar { background-color: transparent; border: none; }")

        self._show_connection_status = bool(show_connection_status)
        self._title = title
        self._patient_name_raw = ""
        self._last_status = DeviceStatus()

        # Single VS5 logo SVG at exact Figma coordinates (31, 24, 87, 92)
        self.vs5_logo = _SvgBadgeWidget(
            "vs5_logo.svg",
            object_name="vs5_logo",
            tint_color=None,
            parent=self,
        )
        self.vs5_logo.setGeometry(
            LAYOUT.LOGO_X,
            LAYOUT.LOGO_Y,
            LAYOUT.LOGO_WIDTH,
            LAYOUT.LOGO_HEIGHT,
        )

        # Active patient label (MainScreen) vs Screen title label (PatientScreen)
        self.lbl_active_patient = QLabel("", self)
        self.lbl_active_patient.setObjectName("lbl_active_patient")
        self.lbl_active_patient.setFont(font_from_token(TYPOGRAPHY.HEADER_PATIENT))
        self.lbl_active_patient.setGeometry(141, 37, 420, 28)
        self.lbl_active_patient.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_screen_title = QLabel("", self)
        self.lbl_screen_title.setObjectName("lbl_screen_title")
        self.lbl_screen_title.setFont(font_from_token(TYPOGRAPHY.SCREEN_TITLE))
        self.lbl_screen_title.setGeometry(139, 24, 360, 41)
        self.lbl_screen_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Live date/time label
        self.lbl_datetime = QLabel("", self)
        self.lbl_datetime.setObjectName("lbl_datetime")
        self.lbl_datetime.setFont(font_from_token(TYPOGRAPHY.HEADER_DATETIME))
        self.lbl_datetime.setGeometry(141, 66, 305, 42)
        self.lbl_datetime.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Cloud icon + non-online status label
        self.cloud_icon = _SvgBadgeWidget(
            "cloud.svg",
            object_name="cloud_icon",
            tint_color=COLORS.CLOUD_ONLINE,
            parent=self,
        )
        self.cloud_icon.setGeometry(452, 78, LAYOUT.CLOUD_WIDTH, LAYOUT.CLOUD_HEIGHT)

        self.lbl_cloud_status = QLabel("", self)
        self.lbl_cloud_status.setObjectName("lbl_cloud_status")
        self.lbl_cloud_status.setFont(font_from_token(TYPOGRAPHY.CONNECTION_STATUS))
        self.lbl_cloud_status.setGeometry(488, 76, 150, 24)
        self.lbl_cloud_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_cloud_status.setVisible(False)

        # UART / ESP32 status label (visible on MainScreen, hidden on PatientScreen)
        self.lbl_uart_status = QLabel(
            "Connected:  UART\nConnected: ESP32",
            self,
        )
        self.lbl_uart_status.setObjectName("lbl_uart_status")
        self.lbl_uart_status.setFont(font_from_token(TYPOGRAPHY.CONNECTION_STATUS))
        self.lbl_uart_status.setGeometry(850, 48, 222, 46)
        self.lbl_uart_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Compact connection fault badge for PatientScreen when UART/ESP32 drops
        self.lbl_compact_conn_badge = QLabel("", self)
        self.lbl_compact_conn_badge.setObjectName("lbl_compact_conn_badge")
        self.lbl_compact_conn_badge.setFont(font_from_token(TYPOGRAPHY.CONNECTION_STATUS))
        self.lbl_compact_conn_badge.setGeometry(800, 56, 272, 32)
        self.lbl_compact_conn_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_compact_conn_badge.setVisible(False)

        # Battery percentage (right-aligned to x=1175, wide enough for "100%") + icon
        self.lbl_battery_pct = QLabel("95%", self)
        self.lbl_battery_pct.setObjectName("lbl_battery_pct")
        self.lbl_battery_pct.setFont(font_from_token(TYPOGRAPHY.BATTERY_PCT))
        self.lbl_battery_pct.setGeometry(1078, 47, 97, 48)
        self.lbl_battery_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.battery_icon = _BatteryIconWidget(self)
        self.battery_icon.setGeometry(1181, 52, LAYOUT.BATTERY_WIDTH, LAYOUT.BATTERY_HEIGHT)

        self.set_title(title)
        self.refresh_clock()
        self.update_device_status(self._last_status)

    def set_title(self, title: str | None) -> None:
        self._title = title
        if title is not None:
            self.lbl_screen_title.setText(title)
            self.lbl_screen_title.setVisible(True)
            self.lbl_active_patient.setVisible(False)
        else:
            self.lbl_screen_title.setVisible(False)
            self.lbl_active_patient.setVisible(True)

    def set_active_patient_name(self, name: str | None) -> None:
        cleaned = (name or "").strip()
        self._patient_name_raw = cleaned
        display = cleaned if cleaned else "No Active Patient"
        elided = self.lbl_active_patient.fontMetrics().elidedText(
            display,
            Qt.TextElideMode.ElideRight,
            max(40, self.lbl_active_patient.width() - 4),
        )
        self.lbl_active_patient.setText(elided)

    def set_patient_name(self, name: str | None) -> None:
        self.set_active_patient_name(name)

    def set_datetime_text(self, text: str) -> None:
        elided = self.lbl_datetime.fontMetrics().elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            max(40, self.lbl_datetime.width() - 4),
        )
        self.lbl_datetime.setText(elided)

    def refresh_clock(self, now: datetime | None = None) -> None:
        dt = now if now is not None else datetime.now()
        day_name = _WEEKDAYS_ID[dt.weekday()]
        self.set_datetime_text(f"{dt:%d/%m} {day_name} {dt:%H:%M}")

    def set_uart_visible(self, visible: bool) -> None:
        self._show_connection_status = bool(visible)
        self._apply_connection_labels(self._last_status)

    def update_device_status(self, status: DeviceStatus) -> None:
        self._last_status = status

        # Battery
        pct = _safe_battery_percent(status.battery_percent)
        if pct is None:
            self.lbl_battery_pct.setText("--%")
            self.lbl_battery_pct.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
            self.battery_icon.set_battery_state(0, is_charging=bool(status.is_charging))
        else:
            self.lbl_battery_pct.setText(f"{pct}%")
            if pct <= 10:
                self.lbl_battery_pct.setStyleSheet(f"color: {COLORS.BATTERY_CRITICAL}; background: transparent;")
            elif pct <= 20:
                self.lbl_battery_pct.setStyleSheet(f"color: {COLORS.BATTERY_LOW}; background: transparent;")
            else:
                self.lbl_battery_pct.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
            self.battery_icon.set_battery_state(pct, is_charging=bool(status.is_charging))

        # Cloud
        if status.cloud_state == CloudState.ONLINE:
            self.cloud_icon.set_tint_color(COLORS.CLOUD_ONLINE)
            self.lbl_cloud_status.setVisible(False)
            self.lbl_cloud_status.setText("")
        elif status.cloud_state == CloudState.OFFLINE:
            self.cloud_icon.set_tint_color(COLORS.CLOUD_OFFLINE)
            self.lbl_cloud_status.setText("Cloud: Offline")
            self.lbl_cloud_status.setStyleSheet(f"color: {COLORS.CLOUD_OFFLINE}; background: transparent;")
            self.lbl_cloud_status.setVisible(True)
        elif status.cloud_state == CloudState.SYNCING:
            self.cloud_icon.set_tint_color(COLORS.BRAND_BLUE)
            self.lbl_cloud_status.setText("Syncing...")
            self.lbl_cloud_status.setStyleSheet(f"color: {COLORS.BRAND_BLUE}; background: transparent;")
            self.lbl_cloud_status.setVisible(True)
        else:
            self.cloud_icon.set_tint_color(COLORS.ALARM_CRITICAL)
            self.lbl_cloud_status.setText("Cloud Error")
            self.lbl_cloud_status.setStyleSheet(f"color: {COLORS.ALARM_CRITICAL}; background: transparent;")
            self.lbl_cloud_status.setVisible(True)

        self._apply_connection_labels(status)

    def set_device_status(self, status: DeviceStatus) -> None:
        self.update_device_status(status)

    def _apply_connection_labels(self, status: DeviceStatus) -> None:
        uart_txt, uart_color = self._format_conn_line("UART", status.uart_state, pad_single=True)
        esp_txt, esp_color = self._format_conn_line("ESP32", status.esp32_state, pad_single=False)
        self.lbl_uart_status.setText(f"{uart_txt}\n{esp_txt}")

        badge_txt, uart_fg = self._format_compact_conn_badge(status)
        self.lbl_uart_status.setStyleSheet(f"color: {uart_fg}; background: transparent;")

        if self._show_connection_status:
            self.lbl_uart_status.setVisible(True)
            self.lbl_compact_conn_badge.setVisible(False)
        else:
            self.lbl_uart_status.setVisible(False)
            if badge_txt:
                self.lbl_compact_conn_badge.setText(badge_txt)
                self.lbl_compact_conn_badge.setStyleSheet(f"color: {uart_fg}; background: transparent;")
                self.lbl_compact_conn_badge.setVisible(True)
            else:
                self.lbl_compact_conn_badge.setVisible(False)

        _ = uart_color, esp_color

    @staticmethod
    def _format_compact_conn_badge(status: DeviceStatus) -> tuple[str, str]:
        uart_disc = status.uart_state == ConnectionState.DISCONNECTED
        esp_disc = status.esp32_state == ConnectionState.DISCONNECTED
        if uart_disc and esp_disc:
            return "UART / ESP32 Disconnected", COLORS.ALARM_CRITICAL
        if uart_disc:
            return "UART Disconnected", COLORS.ALARM_CRITICAL
        if esp_disc:
            return "ESP32 Disconnected", COLORS.ALARM_CRITICAL

        uart_reconn = status.uart_state == ConnectionState.RECONNECTING
        esp_reconn = status.esp32_state == ConnectionState.RECONNECTING
        if uart_reconn and esp_reconn:
            return "UART / ESP32 Reconnecting", COLORS.ALARM_WARNING
        if uart_reconn:
            return "UART Reconnecting", COLORS.ALARM_WARNING
        if esp_reconn:
            return "ESP32 Reconnecting", COLORS.ALARM_WARNING

        return "", COLORS.TEXT_PRIMARY

    @staticmethod
    def _format_conn_line(
        label: str,
        state: ConnectionState,
        *,
        pad_single: bool,
    ) -> tuple[str, str]:
        if state == ConnectionState.CONNECTED:
            sep = "  " if pad_single else " "
            return f"Connected:{sep}{label}", COLORS.TEXT_PRIMARY
        if state == ConnectionState.RECONNECTING:
            return f"Reconnecting: {label}", COLORS.ALARM_WARNING
        return f"Disconnected: {label}", COLORS.ALARM_CRITICAL


__all__ = ["StatusHeaderBar"]
