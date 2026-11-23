"""Bundled JetBrains Mono font registration and static asset path resolution."""

from __future__ import annotations

import os
import weakref
from pathlib import Path

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication

from .tokens import FontToken

FONT_FAMILY = "JetBrains Mono"

BUNDLED_FONT_FILES: tuple[str, ...] = (
    "JetBrainsMono-ExtraLight.ttf",
    "JetBrainsMono-Light.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf",
    "JetBrainsMono-SemiBold.ttf",
    "JetBrainsMono-Bold.ttf",
)

_LOADED_FONT_CACHE: weakref.WeakKeyDictionary[QCoreApplication, dict[Path, list[int]]] = (
    weakref.WeakKeyDictionary()
)


def get_assets_dir() -> Path:
    """Return the root assets directory, honoring ``VITALSENSE5_ASSETS_DIR`` if set."""
    override = os.environ.get("VITALSENSE5_ASSETS_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "assets"


def get_fonts_dir() -> Path:
    """Return the bundled fonts directory."""
    return get_assets_dir() / "fonts"


def get_icons_dir() -> Path:
    """Return the bundled icons directory."""
    return get_assets_dir() / "icons"


def get_icon_path(filename: str) -> Path:
    """Return the absolute path to a bundled SVG icon asset."""
    path = get_icons_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"Bundled icon not found: {path}")
    return path


def load_bundled_fonts(fonts_dir: Path | None = None) -> list[int]:
    """Register all bundled JetBrains Mono weights with Qt's QFontDatabase.

    Must be called after a ``QGuiApplication`` / ``QApplication`` instance exists.
    Repeated calls for the same application instance and directory are idempotent.
    """
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError(
            "QGuiApplication or QApplication must be created before calling load_bundled_fonts()."
        )

    resolved_dir = (fonts_dir if fonts_dir is not None else get_fonts_dir()).resolve()
    app_cache = _LOADED_FONT_CACHE.get(app)
    if (
        app_cache is not None
        and resolved_dir in app_cache
        and FONT_FAMILY in QFontDatabase.families()
    ):
        return list(app_cache[resolved_dir])

    font_ids: list[int] = []
    for filename in BUNDLED_FONT_FILES:
        font_path = resolved_dir / filename
        if not font_path.is_file():
            raise FileNotFoundError(f"Bundled font file missing: {font_path}")
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            raise RuntimeError(f"QFontDatabase failed to load font: {font_path}")
        font_ids.append(font_id)

    _LOADED_FONT_CACHE.setdefault(app, {})[resolved_dir] = font_ids
    return list(font_ids)


def jetbrains_mono_font(
    size_px: int,
    weight: QFont.Weight | int = QFont.Weight.Normal,
    letter_spacing_px: float = 0.0,
) -> QFont:
    """Create a pixel-sized ``JetBrains Mono`` QFont with explicit weight and tracking."""
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size_px)
    font.setWeight(QFont.Weight(weight))
    if letter_spacing_px != 0.0:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing_px)
    return font


def font_from_token(token: FontToken) -> QFont:
    """Construct a ``QFont`` directly from a ``TYPOGRAPHY`` ``FontToken``."""
    return jetbrains_mono_font(
        size_px=token.size_px,
        weight=token.weight,
        letter_spacing_px=token.letter_spacing_px,
    )


__all__ = [
    "BUNDLED_FONT_FILES",
    "FONT_FAMILY",
    "font_from_token",
    "get_assets_dir",
    "get_fonts_dir",
    "get_icon_path",
    "get_icons_dir",
    "jetbrains_mono_font",
    "load_bundled_fonts",
]
