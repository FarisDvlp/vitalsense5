"""Live PPG waveform grid canvas widget for VitalSense5."""

from __future__ import annotations

import math
from collections.abc import Sequence

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QLabel, QWidget

from vitalsense5.contracts.models import (
    ConnectionState,
    DeviceStatus,
    SensorState,
    WaveformBatch,
)
from vitalsense5.theme import BORDERS, COLORS, LAYOUT, jetbrains_mono_font


class PPGCanvasWidget(QWidget):
    """1124x250 ICU-style sweeping PPG waveform canvas with 0.5s grid and fault overlays."""

    def __init__(
        self,
        *,
        sample_rate_hz: float = 200.0,
        window_seconds: float = 10.0,
        gap_seconds: float = 0.25,
        max_samples: int | None = None,
        gap_samples: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ppg_canvas")
        self.setFixedSize(LAYOUT.PPG_WIDTH, LAYOUT.PPG_HEIGHT)
        self.setStyleSheet("#ppg_canvas { background: transparent; border: none; }")

        self._sample_rate_hz = max(1.0, float(sample_rate_hz))
        self._window_seconds = max(0.5, float(window_seconds))
        self._gap_seconds = max(0.0, float(gap_seconds))

        if max_samples is not None:
            self._max_samples = max(16, int(max_samples))
        else:
            self._max_samples = max(16, int(round(self._sample_rate_hz * self._window_seconds)))

        if gap_samples is not None:
            self._gap_samples = max(0, min(self._max_samples - 1, int(gap_samples)))
        else:
            ratio = self._gap_seconds / self._window_seconds
            self._gap_samples = max(0, min(self._max_samples - 1, int(round(self._max_samples * ratio))))

        self._slots: list[float | None] = [None] * self._max_samples
        self._write_idx = 0
        self._has_wrapped = False
        self._last_written_idx: int | None = None
        self._clear_on_next_sample = False

        self._device_status = DeviceStatus()
        self._suppress_trace = False
        self._overlay_mode: str = "none"

        self.lbl_ppg_overlay = QLabel("", self)
        self.lbl_ppg_overlay.setObjectName("lbl_ppg_overlay")
        self.lbl_ppg_overlay.setFont(jetbrains_mono_font(size_px=18, weight=500))
        self.lbl_ppg_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ppg_overlay.setVisible(False)
        self._position_overlay()

    @property
    def max_samples(self) -> int:
        return self._max_samples

    @property
    def gap_samples(self) -> int:
        return self._gap_samples

    @property
    def sweep_index(self) -> int:
        return self._write_idx

    def _reset_sweep_buffer(self) -> None:
        self._slots = [None] * self._max_samples
        self._write_idx = 0
        self._has_wrapped = False
        self._last_written_idx = None

    def samples(self) -> list[float]:
        if not self._has_wrapped:
            return [s for s in self._slots[: self._write_idx] if s is not None]
        ordered = self._slots[self._write_idx :] + self._slots[: self._write_idx]
        return [s for s in ordered if s is not None]

    def append_samples(self, samples: Sequence[float]) -> None:
        added = False
        for raw in samples:
            if isinstance(raw, bool):
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(val):
                continue
            if self._clear_on_next_sample:
                self._reset_sweep_buffer()
                self._clear_on_next_sample = False
            clamped = max(-1.0, min(1.0, val))
            self._slots[self._write_idx] = clamped
            self._last_written_idx = self._write_idx
            next_idx = self._write_idx + 1
            if next_idx >= self._max_samples:
                self._write_idx = 0
                self._has_wrapped = True
            else:
                self._write_idx = next_idx
            added = True
        if added:
            self.update()

    def append_batch(self, batch: WaveformBatch) -> None:
        if batch.samples:
            self.append_samples(batch.samples)

    def set_batch(self, batch: WaveformBatch) -> None:
        self.append_batch(batch)

    def clear_waveform(self) -> None:
        if self._has_wrapped or self._write_idx > 0 or self._last_written_idx is not None:
            self._reset_sweep_buffer()
            self._clear_on_next_sample = False
            self.update()

    def clear(self) -> None:
        self.clear_waveform()

    def update_device_status(self, status: DeviceStatus) -> None:
        self._device_status = status

        if (
            status.uart_state == ConnectionState.DISCONNECTED
            or status.esp32_state == ConnectionState.DISCONNECTED
        ):
            self._suppress_trace = True
            self._clear_on_next_sample = True
            self._overlay_mode = "center"
            self._style_overlay(
                "UART / ESP32 DISCONNECTED",
                COLORS.ALARM_CRITICAL,
            )
        elif (
            status.uart_state == ConnectionState.RECONNECTING
            or status.esp32_state == ConnectionState.RECONNECTING
        ):
            self._suppress_trace = True
            self._clear_on_next_sample = True
            self._overlay_mode = "center"
            self._style_overlay(
                "RECONNECTING UART / ESP32...",
                COLORS.ALARM_WARNING,
            )
        elif status.sensor_state == SensorState.FINGER_OFF:
            self._suppress_trace = True
            self._clear_on_next_sample = True
            self._overlay_mode = "center"
            self._style_overlay(
                "FINGER OFF — SENSOR DETACHED",
                COLORS.ALARM_CRITICAL,
            )
        elif status.sensor_state == SensorState.CALIBRATING:
            self._suppress_trace = False
            self._overlay_mode = "center"
            self._style_overlay(
                "CALIBRATING SENSOR...",
                COLORS.BRAND_BLUE,
            )
        elif status.sensor_state == SensorState.POOR_SIGNAL:
            self._suppress_trace = False
            self._overlay_mode = "top_right"
            self._style_overlay(
                "POOR SIGNAL QUALITY",
                COLORS.ALARM_WARNING,
            )
        else:
            self._suppress_trace = False
            self._overlay_mode = "none"
            self.lbl_ppg_overlay.setVisible(False)
            self.lbl_ppg_overlay.setText("")

        self._position_overlay()
        self.update()

    def set_device_status(self, status: DeviceStatus) -> None:
        self.update_device_status(status)

    def _style_overlay(self, text: str, border_fg_hex: str) -> None:
        self.lbl_ppg_overlay.setText(text)
        self.lbl_ppg_overlay.setStyleSheet(
            f"#lbl_ppg_overlay {{"
            f" background-color: rgba(237, 237, 237, 230);"
            f" border: 2px solid {border_fg_hex};"
            f" border-radius: 8px;"
            f" color: {border_fg_hex};"
            f" padding: 0 12px;"
            f"}}"
        )
        self.lbl_ppg_overlay.setVisible(True)

    def _position_overlay(self) -> None:
        w = self.width()
        h = self.height()
        if self._overlay_mode == "top_right":
            badge_w = min(276, max(180, w - 28))
            badge_h = 34
            self.lbl_ppg_overlay.setGeometry(w - badge_w - 14, 14, badge_w, badge_h)
        else:
            banner_w = min(560, max(240, w - 40))
            banner_h = 42
            self.lbl_ppg_overlay.setGeometry(
                (w - banner_w) // 2,
                (h - banner_h) // 2,
                banner_w,
                banner_h,
            )

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._position_overlay()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        bw = BORDERS.PPG_OUTER_WIDTH

        # 1. Outer 5px #D2D2D2 border
        painter.fillRect(QRect(0, 0, w, h), QColor(COLORS.PPG_BORDER))

        inner = QRect(bw, bw, max(1, w - 2 * bw), max(1, h - 2 * bw))
        painter.save()
        painter.setClipRect(inner)

        # 2. Inner #E4E4E4 background
        painter.fillRect(inner, QColor(COLORS.PPG_BG))

        # 3. 2px #C9C9C9 grid (0.5s horizontal intervals across window_seconds)
        grid_pen = QPen(QColor(COLORS.PPG_GRID), BORDERS.PPG_GRID_LINE_WIDTH)
        painter.setPen(grid_pen)

        grid_cols = max(1, int(round(self._window_seconds / 0.5)))
        col_step = float(inner.width()) / float(grid_cols)
        for col in range(1, grid_cols):
            xi = int(round(float(inner.left()) + col * col_step))
            if xi < inner.right():
                painter.drawLine(xi, inner.top(), xi, inner.bottom())

        y_pos = float(inner.top()) + float(LAYOUT.PPG_GRID_V_SPACING)
        while y_pos < float(inner.bottom()):
            yi = int(round(y_pos))
            painter.drawLine(inner.left(), yi, inner.right(), yi)
            y_pos += float(LAYOUT.PPG_GRID_V_SPACING)

        # 4. 2px #313131 antialiased ICU-sweep PPG waveform trace + 0.25s blank erase gap
        if not self._suppress_trace and self._last_written_idx is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            trace_pen = QPen(QColor(COLORS.PPG_TRACE), BORDERS.PPG_TRACE_WIDTH)
            trace_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            trace_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(trace_pen)

            left_x = float(inner.left() + 2)
            usable_w = max(1.0, float(inner.width() - 4))
            step_x = usable_w / max(1, self._max_samples - 1)
            mid_y = float(inner.top()) + float(inner.height()) / 2.0
            amp_y = max(4.0, (float(inner.height()) / 2.0) - 16.0)
            min_y = float(inner.top() + 2)
            max_y = float(inner.bottom() - 2)

            def _point_at(idx: int) -> QPointF:
                raw_val = self._slots[idx]
                val = 0.0 if raw_val is None else max(-1.0, min(1.0, raw_val))
                px = left_x + idx * step_x
                py = max(min_y, min(max_y, mid_y - val * amp_y))
                return QPointF(px, py)

            def _draw_segment(start_idx: int, end_idx: int) -> None:
                if end_idx - start_idx + 1 < 2:
                    return
                path = QPainterPath()
                path.moveTo(_point_at(start_idx))
                for idx in range(start_idx + 1, end_idx + 1):
                    path.lineTo(_point_at(idx))
                painter.drawPath(path)

            if not self._has_wrapped:
                _draw_segment(0, self._write_idx - 1)
            else:
                gap = self._gap_samples
                gap_end = self._write_idx + gap
                if gap_end <= self._max_samples:
                    # Segment 1: left of sweep cursor [0 .. write_idx - 1]
                    if self._write_idx >= 2:
                        _draw_segment(0, self._write_idx - 1)
                    # Segment 2: right of erase gap [gap_end .. max_samples - 1]
                    if self._max_samples - gap_end >= 2:
                        _draw_segment(gap_end, self._max_samples - 1)
                else:
                    # Erase gap wraps past right edge into [0 .. wrapped_end - 1]
                    wrapped_start = gap_end - self._max_samples
                    if self._write_idx - wrapped_start >= 2:
                        _draw_segment(wrapped_start, self._write_idx - 1)

            # Subtle leading-edge dot on newest sample
            dot_pt = _point_at(self._last_written_idx)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS.PPG_TRACE))
            painter.drawEllipse(dot_pt, 3.0, 3.0)

        painter.restore()
        painter.end()


__all__ = ["PPGCanvasWidget"]
