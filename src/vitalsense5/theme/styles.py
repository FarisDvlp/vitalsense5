"""Pure QSS builder helpers matching the VitalSense-5 Figma design."""

from __future__ import annotations

from typing import Literal

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QWidget

from .fonts import FONT_FAMILY
from .tokens import BORDERS, COLORS, LAYOUT, RADII, clamp_pill_radius

_DEFAULT_CONTAINER_SELECTOR = ".QFrame, .QWidget"


def _validate_selector(selector: str) -> str:
    stripped = selector.strip()
    if not stripped:
        raise ValueError("QSS selector must be a non-empty string.")
    return stripped


def app_base_qss() -> str:
    """Base stylesheet for the application canvas and primary typography.

    Foreground ``color`` is intentionally scoped off ``QWidget`` onto
    ``QLabel`` and non-``QLineEdit`` text controls so Qt 6's
    ``QStyleSheetStyle`` does not overwrite ``QPalette.PlaceholderText``
    on nested ``QLineEdit`` widgets.
    """
    return (
        f"QWidget {{"
        f" background-color: {COLORS.SCREEN_BG};"
        f" font-family: '{FONT_FAMILY}';"
        f"}}"
        f"QLabel {{"
        f" background-color: transparent;"
        f" color: {COLORS.TEXT_PRIMARY};"
        f"}}"
        f"QPushButton, QComboBox, QCheckBox, QRadioButton {{"
        f" color: {COLORS.TEXT_PRIMARY};"
        f"}}"
    )


def action_button_qss(
    variant: Literal["default", "danger", "success"] = "default",
    *,
    pressed: bool = False,
) -> str:
    """Return QSS for 212x51 action buttons with Figma normal and pressed states."""
    if variant == "default":
        normal_bg = COLORS.BTN_DEFAULT_BG
        normal_fg = COLORS.BTN_DEFAULT_TEXT
        pressed_bg = COLORS.BTN_PRESSED_BG
        pressed_fg = COLORS.BTN_PRESSED_TEXT
    elif variant == "danger":
        normal_bg = COLORS.BTN_DANGER_BG
        normal_fg = COLORS.BTN_DEFAULT_TEXT
        pressed_bg = COLORS.BTN_DANGER_PRESSED_BG
        pressed_fg = COLORS.BTN_DEFAULT_TEXT
    elif variant == "success":
        normal_bg = COLORS.BTN_SUCCESS_BG
        normal_fg = COLORS.BTN_DEFAULT_TEXT
        pressed_bg = COLORS.BTN_SUCCESS_PRESSED_BG
        pressed_fg = COLORS.BTN_DEFAULT_TEXT
    else:
        raise ValueError(f"Unsupported action button variant: {variant!r}")

    initial_bg = pressed_bg if pressed else normal_bg
    initial_fg = pressed_fg if pressed else normal_fg

    return (
        f"QPushButton {{"
        f" background-color: {initial_bg};"
        f" color: {initial_fg};"
        f" border: none;"
        f" border-radius: {RADII.ACTION_BUTTON}px;"
        f" font-family: '{FONT_FAMILY}';"
        f" font-size: 24px;"
        f" font-weight: 300;"
        f"}}"
        f"QPushButton:pressed, QPushButton[pressed=\"true\"] {{"
        f" background-color: {pressed_bg};"
        f" color: {pressed_fg};"
        f"}}"
    )


def modal_card_qss(
    radius: int = RADII.MODAL_CARD,
    background: str = COLORS.SURFACE_CARD,
    *,
    selector: str = _DEFAULT_CONTAINER_SELECTOR,
) -> str:
    """Return scoped QSS for modal card surfaces (Settings & New/Edit Patient Pop Up).

    Note: The default selector (``.QFrame, .QWidget``) targets exact ``QFrame``
    and ``QWidget`` instances only. Custom subclasses in M3/M4 must pass
    ``selector="#<objectName>"``.
    """
    target = _validate_selector(selector)
    return (
        f"{target} {{"
        f" background-color: {background};"
        f" border-radius: {radius}px;"
        f" border: none;"
        f"}}"
    )


def modal_scrim_qss(*, selector: str = _DEFAULT_CONTAINER_SELECTOR) -> str:
    """Return scoped QSS for translucent dark modal backdrop scrims.

    Note: The default selector (``.QFrame, .QWidget``) targets exact ``QFrame``
    and ``QWidget`` instances only. Custom subclasses in M3/M4 must pass
    ``selector="#<objectName>"``.
    """
    target = _validate_selector(selector)
    return f"{target} {{ background-color: {COLORS.MODAL_SCRIM}; border: none; }}"


def input_pill_qss(
    *,
    height_px: int = LAYOUT.INPUT_PILL_HEIGHT,
    invalid: bool = False,
) -> str:
    """Return QSS for pill-shaped modal text/numeric inputs with clamped radius."""
    radius = clamp_pill_radius(RADII.INPUT_PILL, height_px)
    border_rule = (
        f"{BORDERS.INPUT_INVALID_WIDTH}px solid {COLORS.INPUT_INVALID_BORDER}"
        if invalid
        else "none"
    )
    return (
        f"QLineEdit {{"
        f" background-color: {COLORS.INPUT_BG};"
        f" border-radius: {radius}px;"
        f" border: {border_rule};"
        f" padding: 0 20px;"
        f" font-family: '{FONT_FAMILY}';"
        f" font-size: 20px;"
        f" font-weight: 200;"
        f"}}"
    )


def apply_input_placeholder_palette(widget: QWidget) -> None:
    """Set QPalette text (#000000) and PlaceholderText (#919191) across color groups."""
    palette = widget.palette()
    text_color = QColor(COLORS.TEXT_PRIMARY)
    placeholder_color = QColor(COLORS.INPUT_PLACEHOLDER)
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        palette.setColor(group, QPalette.ColorRole.Text, text_color)
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, placeholder_color)
    widget.setPalette(palette)


def patient_card_qss(
    *,
    selected: bool = False,
    selector: str = _DEFAULT_CONTAINER_SELECTOR,
) -> str:
    """Return scoped QSS for Patient Screen list cards with optional #226DAA border.

    Note: The default selector (``.QFrame, .QWidget``) targets exact ``QFrame``
    and ``QWidget`` instances only. Custom subclasses in M3/M4 must pass
    ``selector="#<objectName>"``.
    """
    target = _validate_selector(selector)
    border_rule = (
        f"{BORDERS.PATIENT_SELECTED_WIDTH}px solid {COLORS.BRAND_BLUE}"
        if selected
        else "none"
    )
    return (
        f"{target} {{"
        f" background-color: {COLORS.SURFACE_CARD};"
        f" border-radius: {RADII.PATIENT_CARD}px;"
        f" border: {border_rule};"
        f"}}"
    )


def scrollbar_qss(variant: Literal["patient", "settings"] = "patient") -> str:
    """Return QSS for custom vertical scrollbars with clamped pill handle radii."""
    if variant == "patient":
        width = LAYOUT.PATIENT_SCROLLBAR_WIDTH
        track_color = COLORS.PATIENT_SCROLL_TRACK
        thumb_color = COLORS.PATIENT_SCROLL_THUMB
        radius = clamp_pill_radius(RADII.PATIENT_SCROLLBAR, width)
    elif variant == "settings":
        width = LAYOUT.SETTINGS_SCROLLBAR_WIDTH
        track_color = COLORS.SETTINGS_SCROLL_TRACK
        thumb_color = COLORS.SETTINGS_SCROLL_THUMB
        radius = clamp_pill_radius(RADII.SETTINGS_SCROLLBAR, width)
    else:
        raise ValueError(f"Unsupported scrollbar variant: {variant!r}")

    return (
        f"QScrollBar:vertical {{"
        f" background: {track_color};"
        f" width: {width}px;"
        f" border-radius: {radius}px;"
        f" margin: 0px;"
        f" border: none;"
        f"}}"
        f"QScrollBar::handle:vertical {{"
        f" background: {thumb_color};"
        f" border-radius: {radius}px;"
        f" min-height: 44px;"
        f"}}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
        f" height: 0px;"
        f" background: none;"
        f" border: none;"
        f"}}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
        f" background: none;"
        f"}}"
    )


def settings_pill_qss(
    *,
    height_px: int = LAYOUT.SETTINGS_PILL_HEIGHT,
    selector: str = _DEFAULT_CONTAINER_SELECTOR,
) -> str:
    """Return scoped QSS for Settings VALUE000 and LIST pill controls.

    Note: The default selector (``.QFrame, .QWidget``) targets exact ``QFrame``
    and ``QWidget`` instances only. Custom subclasses in M3/M4 must pass
    ``selector="#<objectName>"``.
    """
    target = _validate_selector(selector)
    radius = clamp_pill_radius(RADII.SETTINGS_PILL, height_px)
    return (
        f"{target} {{"
        f" background-color: {COLORS.SETTINGS_PILL_BG};"
        f" color: {COLORS.TEXT_PRIMARY};"
        f" border: none;"
        f" border-radius: {radius}px;"
        f" font-family: '{FONT_FAMILY}';"
        f" font-size: 16px;"
        f" font-weight: 300;"
        f"}}"
    )


def vital_accent_bar_qss(
    color_hex: str,
    *,
    selector: str = _DEFAULT_CONTAINER_SELECTOR,
) -> str:
    """Return scoped QSS for the 5px vertical vital sign accent bar.

    Note: The default selector (``.QFrame, .QWidget``) targets exact ``QFrame``
    and ``QWidget`` instances only. Custom subclasses in M3/M4 must pass
    ``selector="#<objectName>"``.
    """
    target = _validate_selector(selector)
    return f"{target} {{ background-color: {color_hex}; border: none; }}"


__all__ = [
    "action_button_qss",
    "app_base_qss",
    "apply_input_placeholder_palette",
    "input_pill_qss",
    "modal_card_qss",
    "modal_scrim_qss",
    "patient_card_qss",
    "scrollbar_qss",
    "settings_pill_qss",
    "vital_accent_bar_qss",
]
