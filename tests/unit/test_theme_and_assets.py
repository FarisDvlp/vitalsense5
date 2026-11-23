"""Unit tests for VitalSense5 M1 theme tokens, bundled JetBrains Mono fonts, QSS, and SVG assets."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QGuiApplication, QImage, QPainter, QPalette
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QLineEdit, QMainWindow, QPushButton, QWidget

import vitalsense5
from vitalsense5.theme import (
    BORDERS,
    BUNDLED_FONT_FILES,
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    RADII,
    TYPOGRAPHY,
    action_button_qss,
    app_base_qss,
    apply_input_placeholder_palette,
    clamp_pill_radius,
    font_from_token,
    get_assets_dir,
    get_fonts_dir,
    get_icon_path,
    get_icons_dir,
    input_pill_qss,
    jetbrains_mono_font,
    load_bundled_fonts,
    modal_card_qss,
    modal_scrim_qss,
    patient_card_qss,
    scrollbar_qss,
    settings_pill_qss,
    vital_accent_bar_qss,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _render_svg_to_image(svg_path: Path, width: int, height: int) -> tuple[QSvgRenderer, QImage]:
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return renderer, image


def _unique_opaque_hex_colors(image: QImage) -> set[str]:
    colors: set[str] = set()
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() > 200:
                colors.add(color.name(QColor.NameFormat.HexRgb).lower())
    return colors


def test_package_version_exposed() -> None:
    assert vitalsense5.__version__ == "0.1.0"


def test_bundled_assets_exist_and_non_empty() -> None:
    fonts_dir = get_fonts_dir()
    icons_dir = get_icons_dir()

    assert fonts_dir.is_dir()
    assert icons_dir.is_dir()

    for font_file in BUNDLED_FONT_FILES:
        path = fonts_dir / font_file
        assert path.is_file(), f"Missing bundled font: {path}"
        assert path.stat().st_size > 100_000

    for icon_file in ("vs5_logo.svg", "cloud.svg", "battery.svg", "dropdown_arrow.svg"):
        icon_path = get_icon_path(icon_file)
        assert icon_path.is_file()
        assert icon_path.stat().st_size > 0

    with pytest.raises(FileNotFoundError):
        get_icon_path("nonexistent_icon.svg")


def test_assets_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VITALSENSE5_ASSETS_DIR", str(tmp_path))
    assert get_assets_dir() == tmp_path
    assert get_fonts_dir() == tmp_path / "fonts"
    assert get_icons_dir() == tmp_path / "icons"


def test_load_bundled_fonts_requires_qapplication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QGuiApplication, "instance", lambda: None)
    with pytest.raises(RuntimeError, match="QGuiApplication"):
        load_bundled_fonts()


def test_load_bundled_fonts_and_all_weights_registered(qapp: QApplication) -> None:
    ids_first = load_bundled_fonts()
    ids_second = load_bundled_fonts()

    assert len(ids_first) == 6
    assert all(font_id != -1 for font_id in ids_first)
    assert ids_first == ids_second
    assert FONT_FAMILY in QFontDatabase.families()

    styles = QFontDatabase.styles(FONT_FAMILY)
    for expected_style in ("ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold"):
        assert expected_style in styles

    expected_weights = (200, 300, 400, 500, 600, 700)
    for weight in expected_weights:
        font = jetbrains_mono_font(24, weight)
        info = QFontInfo(font)
        assert info.family() == FONT_FAMILY
        assert info.weight() == weight
        assert info.exactMatch() is True


def test_font_from_token_and_pi_letter_spacing(qapp: QApplication) -> None:
    load_bundled_fonts()
    pi_font = font_from_token(TYPOGRAPHY.VITAL_VALUE_PI)
    assert pi_font.pixelSize() == 96
    assert pi_font.weight() == 300
    assert pi_font.letterSpacingType() == QFont.SpacingType.AbsoluteSpacing
    assert pi_font.letterSpacing() == pytest.approx(-3.84, abs=0.02)

    title_font = font_from_token(TYPOGRAPHY.SCREEN_TITLE)
    assert title_font.pixelSize() == 32
    assert title_font.weight() == 700
    assert QFontInfo(title_font).exactMatch() is True


def test_exact_figma_tokens_and_pill_radius_clamping() -> None:
    assert LAYOUT.WINDOW_WIDTH == 1280
    assert LAYOUT.WINDOW_HEIGHT == 720
    assert LAYOUT.TOUCH_MIN_TARGET >= 44
    assert LAYOUT.TOUCH_DRAG_THRESHOLD_PX == 8

    assert COLORS.SCREEN_BG == "#EDEDED"
    assert COLORS.SURFACE_CARD == "#D9D9D9"
    assert COLORS.BTN_PRESSED_BG == "#3F3F3F"
    assert COLORS.BTN_PRESSED_TEXT == "#D9D9D9"
    assert COLORS.BTN_DANGER_BG == "#FF7F7F"
    assert COLORS.BTN_SUCCESS_BG == "#90FF93"
    assert COLORS.ACCENT_PRV == "#CD5656"
    assert COLORS.ACCENT_RR == "#E98D62"
    assert COLORS.ACCENT_PI == "#B369D3"
    assert COLORS.ACCENT_SPO2 == "#64C25E"
    assert COLORS.ACCENT_BP == "#4E54A7"
    assert COLORS.BRAND_BLUE == "#226DAA"
    assert COLORS.BRAND_CYAN == "#1EB5D7"
    assert COLORS.BATTERY_FILL == "#B9FF7F"
    assert COLORS.BATTERY_BORDER == "#59C461"
    assert COLORS.CLOUD_ONLINE == "#0F172A"

    assert BORDERS.PATIENT_SELECTED_WIDTH == 3
    assert BORDERS.PPG_OUTER_WIDTH == 5
    assert BORDERS.VITAL_ACCENT_WIDTH == 5

    assert clamp_pill_radius(RADII.INPUT_PILL, LAYOUT.INPUT_PILL_HEIGHT) == 29
    assert clamp_pill_radius(RADII.SETTINGS_PILL, LAYOUT.SETTINGS_PILL_HEIGHT) == 15
    assert clamp_pill_radius(RADII.PATIENT_SCROLLBAR, LAYOUT.PATIENT_SCROLLBAR_WIDTH) == 14
    assert clamp_pill_radius(RADII.SETTINGS_SCROLLBAR, LAYOUT.SETTINGS_SCROLLBAR_WIDTH) == 6

    with pytest.raises(ValueError):
        clamp_pill_radius(10, -1)


def test_qss_builders_and_pressed_state_strings() -> None:
    assert COLORS.SCREEN_BG in app_base_qss()
    assert FONT_FAMILY in app_base_qss()

    default_qss = action_button_qss("default")
    assert COLORS.BTN_DEFAULT_BG in default_qss
    assert COLORS.BTN_PRESSED_BG in default_qss
    assert COLORS.BTN_PRESSED_TEXT in default_qss
    assert "border-radius: 10px" in default_qss

    pressed_qss = action_button_qss("default", pressed=True)
    assert f"background-color: {COLORS.BTN_PRESSED_BG}" in pressed_qss

    assert COLORS.BTN_DANGER_BG in action_button_qss("danger")
    assert COLORS.BTN_SUCCESS_BG in action_button_qss("success")
    with pytest.raises(ValueError):
        action_button_qss("unknown")  # type: ignore[arg-type]

    assert "border: 3px solid #226DAA" in patient_card_qss(selected=True)
    assert "border: none" in patient_card_qss(selected=False)
    assert "border-radius: 15px" in modal_card_qss()
    assert COLORS.MODAL_SCRIM in modal_scrim_qss()
    assert "border-radius: 15px" in settings_pill_qss()
    assert "border-radius: 14px" in scrollbar_qss("patient")
    assert "border-radius: 6px" in scrollbar_qss("settings")
    assert COLORS.ACCENT_PRV in vital_accent_bar_qss(COLORS.ACCENT_PRV)
    assert COLORS.INPUT_INVALID_BORDER in input_pill_qss(invalid=True)

    with pytest.raises(ValueError):
        scrollbar_qss("invalid")  # type: ignore[arg-type]

    assert ".QFrame, .QWidget" in patient_card_qss(selected=True)
    assert patient_card_qss(selected=True, selector="#patient_card").startswith("#patient_card {")
    assert modal_card_qss(selector="#modal").startswith("#modal {")
    assert modal_scrim_qss(selector="#scrim").startswith("#scrim {")
    assert settings_pill_qss(selector="#pill").startswith("#pill {")
    assert vital_accent_bar_qss(COLORS.ACCENT_PRV, selector="#bar").startswith("#bar {")

    with pytest.raises(ValueError):
        patient_card_qss(selector="   ")
    with pytest.raises(ValueError):
        modal_card_qss(selector="")


def test_rendered_pill_corner_and_pressed_button_pixels(qapp: QApplication) -> None:
    load_bundled_fonts()

    # Verify clamped pill border-radius renders rounded corners (not square fallback)
    container = QWidget()
    container.setFixedSize(300, 90)
    container.setStyleSheet(f"background-color: {COLORS.SURFACE_CARD};")

    line_edit = QLineEdit(container)
    line_edit.setGeometry(18, 15, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
    line_edit.setStyleSheet(input_pill_qss())

    pixmap = container.grab()
    image = pixmap.toImage()
    top_left_corner = image.pixelColor(18, 15).name(QColor.NameFormat.HexRgb).lower()
    center_pixel = image.pixelColor(18 + 132, 15 + 29).name(QColor.NameFormat.HexRgb).lower()

    assert top_left_corner == COLORS.SURFACE_CARD.lower()
    assert center_pixel == COLORS.INPUT_BG.lower()

    # Verify pressed button QSS renders #3F3F3F
    btn = QPushButton("PATIENT")
    btn.setFixedSize(LAYOUT.ACTION_BTN_WIDTH, LAYOUT.ACTION_BTN_HEIGHT)
    btn.setStyleSheet(action_button_qss("default", pressed=True))
    btn_img = btn.grab().toImage()
    btn_bg = btn_img.pixelColor(10, 25).name(QColor.NameFormat.HexRgb).lower()
    assert btn_bg == COLORS.BTN_PRESSED_BG.lower()


def test_app_base_qss_keeps_child_label_transparent_on_card_surface(qapp: QApplication) -> None:
    load_bundled_fonts()

    host = QWidget()
    host.setFixedSize(360, 140)
    host.setStyleSheet(app_base_qss())

    card = QFrame(host)
    card.setObjectName("card")
    card.setGeometry(20, 20, 320, 100)
    card.setStyleSheet(f"#card {{ background-color: {COLORS.SURFACE_CARD}; border-radius: 14px; }}")

    lbl = QLabel("Patient 1", card)
    lbl.setGeometry(20, 20, 260, 50)

    img = host.grab().toImage()
    assert img.pixelColor(5, 5).name(QColor.NameFormat.HexRgb).lower() == COLORS.SCREEN_BG.lower()
    # Top-left interior of the QLabel must show the #D9D9D9 card surface, NOT opaque #EDEDED
    label_bg = img.pixelColor(42, 42).name(QColor.NameFormat.HexRgb).lower()
    assert label_bg == COLORS.SURFACE_CARD.lower()
    assert label_bg != COLORS.SCREEN_BG.lower()


def test_container_qss_does_not_cascade_to_child_labels(qapp: QApplication) -> None:
    load_bundled_fonts()

    # 1. Selected patient card QFrame has #226DAA border, child QLabel must NOT inherit border
    host = QWidget()
    host.setFixedSize(440, 111)
    host.setStyleSheet(app_base_qss())

    card = QFrame(host)
    card.setGeometry(20, 20, 400, 71)
    card.setStyleSheet(patient_card_qss(selected=True))

    lbl = QLabel("Patient Number 1", card)
    lbl.setGeometry(20, 15, 240, 40)

    img = host.grab().toImage()
    # Outer border of QFrame renders #226DAA
    assert img.pixelColor(220, 21).name(QColor.NameFormat.HexRgb).lower() == COLORS.BRAND_BLUE.lower()
    # Child QLabel area must contain zero #226DAA border pixels
    for y in range(35, 75):
        for x in range(40, 280):
            px = img.pixelColor(x, y).name(QColor.NameFormat.HexRgb).lower()
            assert px != COLORS.BRAND_BLUE.lower(), f"Unexpected #226DAA cascade at ({x}, {y})"
    assert img.pixelColor(42, 36).name(QColor.NameFormat.HexRgb).lower() == COLORS.SURFACE_CARD.lower()

    # 2. Modal scrim + modal card + settings pill + vital accent bar do not cascade onto child QLabel
    scrim = QWidget()
    scrim.setFixedSize(400, 260)
    scrim.setStyleSheet(modal_scrim_qss())

    modal = QFrame(scrim)
    modal.setGeometry(30, 30, 340, 200)
    modal.setStyleSheet(modal_card_qss())

    modal_lbl = QLabel("SETTINGS", modal)
    modal_lbl.setGeometry(20, 15, 160, 30)

    pill = QFrame(modal)
    pill.setGeometry(20, 60, 160, 31)
    pill.setStyleSheet(settings_pill_qss())
    pill_lbl = QLabel("VALUE", pill)
    pill_lbl.setGeometry(8, 4, 80, 22)
    pill_lbl.setAutoFillBackground(True)
    pill_pal = pill_lbl.palette()
    pill_pal.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
    pill_lbl.setPalette(pill_pal)

    accent = QFrame(modal)
    accent.setGeometry(20, 110, 80, 40)
    accent.setStyleSheet(vital_accent_bar_qss(COLORS.ACCENT_PRV))
    accent_lbl = QLabel("", accent)
    accent_lbl.setGeometry(10, 5, 40, 20)
    accent_lbl.setAutoFillBackground(True)
    accent_pal = accent_lbl.palette()
    accent_pal.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
    accent_lbl.setPalette(accent_pal)

    scrim_img = scrim.grab().toImage()
    # Modal label background shows #D9D9D9 card (not darkened scrim)
    assert scrim_img.pixelColor(52, 46).name(QColor.NameFormat.HexRgb).lower() == COLORS.SURFACE_CARD.lower()
    # Child QLabels inside settings_pill_qss and vital_accent_bar_qss keep their own #FFFFFF palette
    assert scrim_img.pixelColor(60, 96).name(QColor.NameFormat.HexRgb).lower() == "#ffffff"
    assert scrim_img.pixelColor(65, 150).name(QColor.NameFormat.HexRgb).lower() == "#ffffff"


def test_apply_input_placeholder_palette_sets_and_renders_919191(qapp: QApplication) -> None:
    load_bundled_fonts()

    line_edit = QLineEdit()
    line_edit.setFixedSize(LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
    line_edit.setPlaceholderText("Name")
    line_edit.setStyleSheet(input_pill_qss())
    apply_input_placeholder_palette(line_edit)

    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        assert (
            line_edit.palette().color(group, QPalette.ColorRole.PlaceholderText).name().lower()
            == COLORS.INPUT_PLACEHOLDER.lower()
        )
        assert (
            line_edit.palette().color(group, QPalette.ColorRole.Text).name().lower()
            == COLORS.TEXT_PRIMARY.lower()
        )

    img = line_edit.grab().toImage()
    rendered_colors = {
        img.pixelColor(x, y).name(QColor.NameFormat.HexRgb).lower()
        for y in range(img.height())
        for x in range(img.width())
    }
    assert COLORS.INPUT_PLACEHOLDER.lower() in rendered_colors
    assert "#7e7e7e" not in rendered_colors
    assert "#000000" not in rendered_colors


def test_nested_line_edit_under_app_base_qss_preserves_919191_placeholder(qapp: QApplication) -> None:
    load_bundled_fonts()

    window = QMainWindow()
    window.setFixedSize(460, 220)
    window.setStyleSheet(app_base_qss())

    central = QWidget(window)
    window.setCentralWidget(central)

    modal = QFrame(central)
    modal.setGeometry(20, 20, 420, 180)
    modal.setStyleSheet(modal_card_qss())

    lbl = QLabel("Name", modal)
    lbl.setGeometry(24, 18, 120, 30)

    le = QLineEdit(modal)
    le.setGeometry(24, 60, 320, LAYOUT.INPUT_PILL_HEIGHT)
    le.setPlaceholderText("Name")
    le.setStyleSheet(input_pill_qss())
    apply_input_placeholder_palette(le)

    assert le.palette().color(QPalette.ColorRole.PlaceholderText).name().lower() == "#919191"

    img_placeholder = window.grab().toImage()

    # Sibling QLabel must render #000000 text over #D9D9D9 modal surface (not #EDEDED)
    label_colors = {
        img_placeholder.pixelColor(x, y).name(QColor.NameFormat.HexRgb).lower()
        for y in range(38, 68)
        for x in range(44, 164)
    }
    assert COLORS.TEXT_PRIMARY.lower() in label_colors
    assert COLORS.SURFACE_CARD.lower() in label_colors
    assert COLORS.SCREEN_BG.lower() not in label_colors

    # Placeholder region inside QLineEdit must preserve #919191 and never degrade to #7E7E7E
    placeholder_colors = {
        img_placeholder.pixelColor(x, y).name(QColor.NameFormat.HexRgb).lower()
        for y in range(85, 134)
        for x in range(54, 354)
    }
    assert "#919191" in placeholder_colors
    assert "#7e7e7e" not in placeholder_colors
    assert "#000000" not in placeholder_colors

    # Re-verify palette after render and confirm typed text renders #000000
    assert le.palette().color(QPalette.ColorRole.PlaceholderText).name().lower() == "#919191"

    le.setText("John Doe")
    img_typed = window.grab().toImage()
    typed_colors = {
        img_typed.pixelColor(x, y).name(QColor.NameFormat.HexRgb).lower()
        for y in range(85, 134)
        for x in range(54, 354)
    }
    assert "#000000" in typed_colors


def test_load_bundled_fonts_reregisters_after_qapplication_recreated() -> None:
    script = (
        "import gc\n"
        "from PyQt6.QtGui import QFontDatabase\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from vitalsense5.theme import FONT_FAMILY, load_bundled_fonts\n"
        "app1 = QApplication([])\n"
        "ids1 = load_bundled_fonts()\n"
        "assert len(ids1) == 6\n"
        "assert FONT_FAMILY in QFontDatabase.families()\n"
        "app1.quit()\n"
        "del app1\n"
        "gc.collect()\n"
        "app2 = QApplication([])\n"
        "assert FONT_FAMILY not in QFontDatabase.families()\n"
        "ids2 = load_bundled_fonts()\n"
        "assert len(ids2) == 6\n"
        "assert FONT_FAMILY in QFontDatabase.families()\n"
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = str(repo_root / "src")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pp}" if existing_pp else src_dir

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_svg_icons_valid_and_render_expected_colors_and_orientation(qapp: QApplication) -> None:
    logo_renderer, logo_img = _render_svg_to_image(get_icon_path("vs5_logo.svg"), 87, 92)
    assert logo_renderer.isValid()
    assert logo_renderer.viewBoxF().width() == pytest.approx(87.0, abs=0.1)
    logo_colors = _unique_opaque_hex_colors(logo_img)
    assert COLORS.BRAND_BLUE.lower() in logo_colors
    assert COLORS.BRAND_CYAN.lower() in logo_colors

    cloud_renderer, cloud_img = _render_svg_to_image(get_icon_path("cloud.svg"), 29, 21)
    assert cloud_renderer.isValid()
    cloud_colors = _unique_opaque_hex_colors(cloud_img)
    assert COLORS.CLOUD_ONLINE.lower() in cloud_colors

    battery_renderer, battery_img = _render_svg_to_image(get_icon_path("battery.svg"), 23, 38)
    assert battery_renderer.isValid()
    assert battery_renderer.viewBoxF() == QRectF(0, 0, 23, 38)
    battery_colors = _unique_opaque_hex_colors(battery_img)
    assert COLORS.BATTERY_BORDER.lower() in battery_colors
    assert COLORS.BATTERY_FILL.lower() in battery_colors

    arrow_renderer, arrow_img = _render_svg_to_image(get_icon_path("dropdown_arrow.svg"), 24, 21)
    assert arrow_renderer.isValid()
    # Downward triangle: top rows must have more opaque dark pixels than bottom apex rows
    top_count = sum(1 for x in range(arrow_img.width()) if arrow_img.pixelColor(x, 2).alpha() > 128)
    bottom_count = sum(1 for x in range(arrow_img.width()) if arrow_img.pixelColor(x, 18).alpha() > 128)
    assert top_count > bottom_count
    assert bottom_count >= 1
