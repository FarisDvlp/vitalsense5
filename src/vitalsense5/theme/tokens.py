"""Exact Figma design tokens, layout geometry, and typography specs for VitalSense5."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Exact hex color palette derived from the VitalSense-5 Figma file and clinical gap mitigations."""

    # Canvas & Surfaces
    SCREEN_BG: str = "#EDEDED"
    SURFACE_CARD: str = "#D9D9D9"
    INPUT_BG: str = "#FDFDFD"
    SETTINGS_PILL_BG: str = "#F0F0F0"
    SETTINGS_SCROLL_TRACK: str = "#FEFEFE"
    MODAL_SCRIM: str = "rgba(0, 0, 0, 102)"

    # Interactive / Buttons
    BTN_DEFAULT_BG: str = "#D9D9D9"
    BTN_DEFAULT_TEXT: str = "#000000"
    BTN_PRESSED_BG: str = "#3F3F3F"
    BTN_PRESSED_TEXT: str = "#D9D9D9"
    BTN_DANGER_BG: str = "#FF7F7F"
    BTN_DANGER_PRESSED_BG: str = "#E05E5E"
    BTN_SUCCESS_BG: str = "#90FF93"
    BTN_SUCCESS_PRESSED_BG: str = "#6CE670"

    # Toggles & Scrollbars
    TOGGLE_OFF: str = "#FF6161"
    TOGGLE_ON: str = "#90FF93"
    TOGGLE_KNOB: str = "#FFFFFF"
    PATIENT_SCROLL_TRACK: str = "#D9D9D9"
    PATIENT_SCROLL_THUMB: str = "#838383"
    SETTINGS_SCROLL_THUMB: str = "#797979"

    # Text & Dividers
    TEXT_PRIMARY: str = "#000000"
    TEXT_SECONDARY: str = "#494949"
    TIMER_TEXT: str = "#868686"
    INPUT_PLACEHOLDER: str = "#919191"
    DIVIDER: str = "#000000"

    # PPG Waveform & Grid
    PPG_BG: str = "#E4E4E4"
    PPG_BORDER: str = "#D2D2D2"
    PPG_GRID: str = "#C9C9C9"
    PPG_TRACE: str = "#313131"

    # Vital Accents & Brand
    ACCENT_PRV: str = "#CD5656"
    ACCENT_RR: str = "#E98D62"
    ACCENT_PI: str = "#B369D3"
    ACCENT_SPO2: str = "#64C25E"
    ACCENT_BP: str = "#4E54A7"
    ACCENT_PR: str = "#B81D1D"
    BRAND_BLUE: str = "#226DAA"
    BRAND_CYAN: str = "#1EB5D7"

    # Status Icons & Clinical Gaps
    BATTERY_FILL: str = "#B9FF7F"
    BATTERY_BORDER: str = "#59C461"
    BATTERY_LOW: str = "#E98D62"
    BATTERY_CRITICAL: str = "#FF6161"
    CLOUD_ONLINE: str = "#0F172A"
    CLOUD_OFFLINE: str = "#919191"
    ALARM_WARNING: str = "#E98D62"
    ALARM_CRITICAL: str = "#FF6161"
    INPUT_INVALID_BORDER: str = "#FF6161"


@dataclass(frozen=True)
class Radii:
    """Raw Figma border-radius tokens (in px)."""

    ACTION_BUTTON: int = 10
    PATIENT_CARD: int = 14
    MODAL_CARD: int = 15
    PATIENT_SCROLLBAR: int = 16
    SETTINGS_SCROLLBAR: int = 10
    SETTINGS_PILL: int = 19
    INPUT_PILL: int = 47
    PPG_BOX: int = 0


def clamp_pill_radius(figma_radius: int, min_dim_px: int) -> int:
    """Clamp a CSS/QSS border-radius to ``min_dim_px // 2``.

    Qt QSS disables ``border-radius`` completely (rendering square corners)
    whenever ``border-radius > min(width, height) / 2``.
    """
    if min_dim_px < 0:
        raise ValueError(f"min_dim_px must be non-negative, got {min_dim_px}")
    return max(0, min(figma_radius, min_dim_px // 2))


@dataclass(frozen=True)
class Borders:
    """Stroke and border width tokens (in px)."""

    PATIENT_SELECTED_WIDTH: int = 3
    PPG_OUTER_WIDTH: int = 5
    PPG_GRID_LINE_WIDTH: int = 2
    PPG_TRACE_WIDTH: int = 2
    VITAL_ACCENT_WIDTH: int = 5
    SETTINGS_DIVIDER_WIDTH: int = 2
    INPUT_INVALID_WIDTH: int = 2


@dataclass(frozen=True)
class Layout:
    """Screen, widget, modal, and touchscreen ergonomics geometry (at 1280x720)."""

    WINDOW_WIDTH: int = 1280
    WINDOW_HEIGHT: int = 720

    # Header
    LOGO_X: int = 31
    LOGO_Y: int = 24
    LOGO_WIDTH: int = 87
    LOGO_HEIGHT: int = 92
    CLOUD_WIDTH: int = 29
    CLOUD_HEIGHT: int = 21
    BATTERY_WIDTH: int = 23
    BATTERY_HEIGHT: int = 38

    # Vitals
    VITAL_ACCENT_HEIGHT: int = 166

    # PPG Waveform Grid
    PPG_X: int = 80
    PPG_Y: int = 348
    PPG_WIDTH: int = 1124
    PPG_HEIGHT: int = 250
    PPG_GRID_V_SPACING: int = 34
    PPG_GRID_H_SPACING: float = 41.766

    # Bottom Action Buttons
    ACTION_BTN_WIDTH: int = 212
    ACTION_BTN_HEIGHT: int = 51

    # Patient List
    PATIENT_CARD_WIDTH: int = 1166
    PATIENT_CARD_HEIGHT: int = 71
    PATIENT_CARD_GAP: int = 10
    PATIENT_CARD_PITCH: int = 81
    PATIENT_SCROLLBAR_WIDTH: int = 28
    PATIENT_SCROLLBAR_HEIGHT: int = 476

    # Modals (Settings & New/Edit Patient Pop Up)
    SETTINGS_MODAL_WIDTH: int = 669
    SETTINGS_MODAL_HEIGHT: int = 437
    SETTINGS_ROW_HEIGHT: int = 48
    SETTINGS_DIVIDER_WIDTH: int = 633
    SETTINGS_PILL_HEIGHT: int = 31
    SETTINGS_TOGGLE_WIDTH: int = 84
    SETTINGS_VALUE_WIDTH: int = 128
    SETTINGS_SCROLLBAR_WIDTH: int = 13
    NEW_PATIENT_MODAL_WIDTH: int = 875
    NEW_PATIENT_MODAL_HEIGHT: int = 231
    INPUT_PILL_HEIGHT: int = 59
    INPUT_NAME_WIDTH: int = 552
    INPUT_GENDER_WIDTH: int = 264
    INPUT_METRIC_WIDTH: int = 264

    # Touch Ergonomics
    TOUCH_MIN_TARGET: int = 44
    TOUCH_DRAG_THRESHOLD_PX: int = 8


@dataclass(frozen=True)
class FontToken:
    """Typography specification for a single UI text role."""

    size_px: int
    weight: int
    letter_spacing_px: float = 0.0


@dataclass(frozen=True)
class Typography:
    """Figma JetBrains Mono typography scale."""

    VITAL_VALUE_LARGE: FontToken = FontToken(96, 300, 0.0)
    VITAL_VALUE_PI: FontToken = FontToken(96, 300, -3.84)
    VITAL_VALUE_BP: FontToken = FontToken(64, 300, 0.0)
    VITAL_HEADER: FontToken = FontToken(48, 200, 0.0)
    BATTERY_PCT: FontToken = FontToken(36, 200, 0.0)
    PR_VALUE: FontToken = FontToken(36, 200, 0.0)
    SCREEN_TITLE: FontToken = FontToken(32, 700, 0.0)
    SETTINGS_TITLE: FontToken = FontToken(32, 400, 0.0)
    HEADER_DATETIME: FontToken = FontToken(32, 300, 0.0)
    PATIENT_CARD_NAME: FontToken = FontToken(32, 300, 0.0)
    VITAL_UNIT_LARGE: FontToken = FontToken(32, 200, 0.0)
    BP_SUBLABEL_UNIT: FontToken = FontToken(24, 200, 0.0)
    ACTION_BUTTON: FontToken = FontToken(24, 300, 0.0)
    RECORDING_TIMER: FontToken = FontToken(24, 300, 0.0)
    SETTINGS_LABEL: FontToken = FontToken(24, 300, 0.0)
    SETTINGS_DONE: FontToken = FontToken(20, 300, 0.0)
    PRV_SUBLABEL: FontToken = FontToken(20, 200, 0.0)
    HEADER_PATIENT: FontToken = FontToken(20, 200, 0.0)
    INPUT_TEXT: FontToken = FontToken(20, 200, 0.0)
    PATIENT_CARD_META: FontToken = FontToken(20, 300, 0.0)
    CONNECTION_STATUS: FontToken = FontToken(16, 200, 0.0)
    PR_UNIT: FontToken = FontToken(16, 200, 0.0)
    SETTINGS_CONTROL: FontToken = FontToken(16, 300, 0.0)


COLORS = Palette()
RADII = Radii()
BORDERS = Borders()
LAYOUT = Layout()
TYPOGRAPHY = Typography()

__all__ = [
    "BORDERS",
    "Borders",
    "COLORS",
    "FontToken",
    "LAYOUT",
    "Layout",
    "Palette",
    "RADII",
    "Radii",
    "TYPOGRAPHY",
    "Typography",
    "clamp_pill_radius",
]
