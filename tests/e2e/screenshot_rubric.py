"""Automated 1280x720 offscreen screenshot capture and visual/geometry rubric for VitalSense5.

CLI usage:
    python -m tests.e2e.screenshot_rubric --out artifacts/screenshots
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


@dataclass
class ScreenCheckResult:
    """Rubric verification outcome for a single captured screen state."""

    screen_name: str
    image_path: Path
    width: int
    height: int
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)


@dataclass
class RubricReport:
    """Aggregated rubric result across all captured VitalSense5 screens."""

    passed: bool
    results: list[ScreenCheckResult] = field(default_factory=list)

    def summary(self) -> str:
        lines: list[str] = [
            f"VitalSense5 1280x720 Screenshot Rubric: {'PASS' if self.passed else 'FAIL'}"
        ]
        for res in self.results:
            status = "PASS" if res.passed else "FAIL"
            lines.append(
                f"  - [{status}] {res.screen_name} ({res.width}x{res.height}) -> {res.image_path}"
            )
            for err in res.errors:
                lines.append(f"      ERROR: {err}")
            for warn in res.warnings:
                lines.append(f"      WARN:  {warn}")
        return "\n".join(lines)


def ensure_offscreen_app() -> Any:
    """Create or reuse offscreen QApplication with 1:1 DPI scaling guards."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(["vitalsense5-rubric"])
    return app


def _ensure_src_on_path() -> None:
    if SRC_DIR.is_dir():
        src_str = str(SRC_DIR)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


def _pump(ms: int = 80) -> None:
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    QTest.qWait(ms)


def _find_widget(root: Any, object_name: str) -> Any | None:
    from PyQt6.QtWidgets import QWidget

    return root.findChild(QWidget, object_name)


def _find_overlay(window: Any, object_name: str) -> Any | None:
    from PyQt6.QtWidgets import QApplication, QWidget

    cand = window.findChild(QWidget, object_name)
    if cand is not None and cand.isVisible():
        return cand
    app = QApplication.instance()
    if app is not None:
        for top in app.topLevelWidgets():
            if top.objectName() == object_name and top.isVisible():
                return top
            nested = top.findChild(QWidget, object_name)
            if nested is not None and nested.isVisible():
                return nested
    return cand


def _click(widget: Any, wait_ms: int = 80) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    center = widget.rect().center()
    target = widget.childAt(center) or widget
    pos = target.mapFrom(widget, center) if target is not widget else center
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QApplication.processEvents()
    QTest.qWait(wait_ms)


def _global_rect(widget: Any, window: Any) -> Any:
    from PyQt6.QtCore import QPoint, QRect

    return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    clean = hex_color.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def _scan_image_metrics(
    img: Any,
    palette_hex: list[str],
    *,
    tolerance: int = 18,
) -> tuple[int, int, dict[str, int], float]:
    """Single-pass stride-2 / stride-4 scan for color buckets, luminance spread, and palette hits."""
    w = img.width()
    h = img.height()
    targets = [(hx, _hex_to_rgb(hx)) for hx in palette_hex]
    counts: dict[str, int] = {hx: 0 for hx in palette_hex}
    tol_sq = tolerance * tolerance

    buckets: set[tuple[int, int, int]] = set()
    min_lum = 255
    max_lum = 0
    ededed_hits = 0
    stride4_total = 0

    for y in range(0, h, 2):
        for x in range(0, w, 2):
            px = img.pixel(x, y)
            r = (px >> 16) & 0xFF
            g = (px >> 8) & 0xFF
            b = px & 0xFF

            for hx, (tr, tg, tb) in targets:
                if (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2 <= tol_sq:
                    counts[hx] += 1

            if x % 4 == 0 and y % 4 == 0:
                stride4_total += 1
                buckets.add((r >> 2, g >> 2, b >> 2))
                lum = (299 * r + 587 * g + 114 * b) // 1000
                if lum < min_lum:
                    min_lum = lum
                if lum > max_lum:
                    max_lum = lum
                if (r - 237) ** 2 + (g - 237) ** 2 + (b - 237) ** 2 <= tol_sq:
                    ededed_hits += 1

    lum_spread = max(0, max_lum - min_lum)
    ededed_fraction = (ededed_hits / stride4_total) if stride4_total else 0.0
    return len(buckets), lum_spread, counts, ededed_fraction


def _check_margin_ededed(img: Any, tolerance: int = 18) -> float:
    probes = [(10, 10), (10, 360), (10, 700), (1270, 10), (1270, 700), (640, 710)]
    tol_sq = tolerance * tolerance
    hits = 0
    for x, y in probes:
        if x < img.width() and y < img.height():
            px = img.pixel(x, y)
            r = (px >> 16) & 0xFF
            g = (px >> 8) & 0xFF
            b = px & 0xFF
            if (r - 237) ** 2 + (g - 237) ** 2 + (b - 237) ** 2 <= tol_sq:
                hits += 1
    return hits / len(probes)


def _check_no_pairwise_overlap(
    items: list[tuple[str, Any]],
    errors: list[str],
    *,
    tolerance_px: int = 2,
    context: str = "",
) -> None:
    for idx_a in range(len(items)):
        name_a, rect_a = items[idx_a]
        for idx_b in range(idx_a + 1, len(items)):
            name_b, rect_b = items[idx_b]
            inter = rect_a.intersected(rect_b)
            if inter.width() > tolerance_px and inter.height() > tolerance_px:
                errors.append(
                    f"{context}Overlap between {name_a} {rect_a.getRect()} and {name_b} {rect_b.getRect()} "
                    f"(intersection {inter.width()}x{inter.height()})"
                )


def _check_window_bounds(
    items: list[tuple[str, Any]],
    errors: list[str],
    *,
    width: int = 1280,
    height: int = 720,
) -> None:
    from PyQt6.QtCore import QRect

    bounds = QRect(0, 0, width, height)
    for name, rect in items:
        if not bounds.contains(rect):
            errors.append(f"Widget {name} rect {rect.getRect()} exceeds 1280x720 window bounds")


def _check_font_and_label_truncation(root: Any, errors: list[str], warnings: list[str]) -> None:
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtWidgets import QLabel

    families = set(QFontDatabase.families())
    if "JetBrains Mono" not in families:
        errors.append("JetBrains Mono font family is not registered in QFontDatabase")

    for lbl in root.findChildren(QLabel):
        if not lbl.isVisible():
            continue
        txt = lbl.text().strip()
        if not txt or lbl.wordWrap() or "\n" in txt:
            continue
        if lbl.width() <= 0 or lbl.height() <= 0:
            continue
        text_w = lbl.fontMetrics().horizontalAdvance(txt)
        if text_w > lbl.width() + 8:
            msg = (
                f"Label {lbl.objectName() or '<unnamed>'!r} text {txt!r} width {text_w}px "
                f"exceeds widget width {lbl.width()}px"
            )
            errors.append(msg)


def _capture_and_check_base(
    window: Any,
    screen_name: str,
    out_dir: Path,
    required_colors: list[str],
    *,
    check_ededed_canvas: bool = False,
) -> tuple[ScreenCheckResult, Any]:
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImage

    img = window.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    out_path = out_dir / f"{screen_name}.png"
    img.save(str(out_path), "PNG")

    errors: list[str] = []
    warnings: list[str] = []

    if window.size() != QSize(1280, 720):
        errors.append(f"Window size is {window.width()}x{window.height()}, expected 1280x720")
    if img.width() != 1280 or img.height() != 720:
        errors.append(f"Captured image size is {img.width()}x{img.height()}, expected 1280x720")

    all_palette = list(dict.fromkeys(required_colors + (["#EDEDED"] if check_ededed_canvas else [])))
    bucket_count, lum_spread, color_counts, ededed_frac = _scan_image_metrics(img, all_palette)

    if bucket_count < 8:
        errors.append(f"Screen appears blank/flat: only {bucket_count} quantized color buckets (< 8)")
    if lum_spread < 40:
        errors.append(f"Low contrast/blank screen: luminance spread {lum_spread} (< 40)")

    if check_ededed_canvas:
        margin_hit_ratio = _check_margin_ededed(img)
        if margin_hit_ratio < 0.75:
            errors.append(f"Canvas margin #EDEDED probe ratio {margin_hit_ratio:.2f} < 0.75")
        if ededed_frac < 0.20:
            errors.append(f"Canvas #EDEDED area fraction {ededed_frac:.2f} < 0.20")

    for hx in required_colors:
        if color_counts.get(hx, 0) < 20:
            errors.append(
                f"Expected Figma color {hx} missing or insufficient ({color_counts.get(hx, 0)} < 20 sampled px)"
            )

    _check_font_and_label_truncation(window, errors, warnings)

    result = ScreenCheckResult(
        screen_name=screen_name,
        image_path=out_path,
        width=img.width(),
        height=img.height(),
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        metrics={
            "color_buckets": bucket_count,
            "luminance_spread": lum_spread,
            "palette_counts": color_counts,
            "ededed_fraction": round(ededed_frac, 3),
        },
    )
    return result, img


def _dismiss_keyboard_if_open(window: Any) -> None:
    from PyQt6.QtWidgets import QAbstractButton

    kb = _find_overlay(window, "virtual_keyboard_overlay")
    if kb is not None and kb.isVisible():
        for btn in kb.findChildren(QAbstractButton):
            if btn.isVisible() and btn.text().strip().upper() in ("DONE", "OK", "HIDE", "CLOSE", "✓"):
                _click(btn, wait_ms=60)
                return
        focused = window.focusWidget()
        if focused is not None:
            focused.clearFocus()
        _pump(60)


def _find_patient_card_rows(patient_screen: Any) -> list[Any]:
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QWidget

    scroll_area = _find_widget(patient_screen, "patient_scroll_area")
    if scroll_area is None or scroll_area.widget() is None:
        return []
    container = scroll_area.widget()
    rows: list[Any] = []
    layout = container.layout()
    if layout is not None:
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None and w.isVisible() and w.width() >= 400 and w.height() >= 50:
                rows.append(w)
    if not rows:
        for child in container.children():
            if isinstance(child, QWidget) and child.isVisible() and child.width() >= 400 and child.height() >= 50:
                rows.append(child)
    rows.sort(key=lambda r: r.mapTo(container, QPoint(0, 0)).y())
    return rows


def run_screenshot_rubric(output_dir: Path | str, window: Any = None) -> RubricReport:
    """Capture 5 VitalSense5 1280x720 screens and run all visual/geometry/non-occlusion checks."""
    from PyQt6.QtWidgets import QAbstractButton, QLabel, QWidget

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    app = ensure_offscreen_app()

    owns_window = window is None
    if window is None:
        _ensure_src_on_path()
        from vitalsense5.main import create_app

        window = create_app(kiosk=False)
        window.resize(1280, 720)
        window.show()
        _pump(220)
    else:
        window.resize(1280, 720)
        if not window.isVisible():
            window.show()
        _pump(150)

    results: list[ScreenCheckResult] = []

    try:
        # ------------------------------------------------------------------
        # 1. MainScreen
        # ------------------------------------------------------------------
        main_res, _ = _capture_and_check_base(
            window,
            "main_screen",
            out_dir,
            required_colors=[
                "#CD5656",
                "#E98D62",
                "#B369D3",
                "#64C25E",
                "#4E54A7",
                "#FF7F7F",
                "#226DAA",
                "#1EB5D7",
                "#E4E4E4",
                "#D9D9D9",
            ],
            check_ededed_canvas=True,
        )
        main_names = [
            "vital_prv",
            "vital_rr",
            "vital_pi",
            "vital_spo2",
            "vital_bp",
            "lbl_source_status",
            "lbl_finger_status",
            "ppg_canvas",
            "btn_patient",
            "btn_settings",
            "btn_record",
        ]
        main_items: list[tuple[str, Any]] = []
        for name in main_names:
            w = _find_widget(window, name)
            if w is None or not w.isVisible():
                main_res.errors.append(f"MainScreen widget {name!r} missing or not visible")
            else:
                main_items.append((name, _global_rect(w, window)))

        header_names = ["lbl_active_patient", "lbl_datetime", "lbl_uart_status", "lbl_battery_pct"]
        header_items: list[tuple[str, Any]] = []
        for name in header_names:
            w = _find_widget(window, name)
            if w is None or not w.isVisible():
                main_res.errors.append(f"MainScreen header label {name!r} missing or not visible")
            else:
                header_items.append((name, _global_rect(w, window)))

        _check_window_bounds(main_items + header_items, main_res.errors)
        _check_no_pairwise_overlap(main_items, main_res.errors, context="MainScreen ")
        _check_no_pairwise_overlap(header_items, main_res.errors, context="MainScreen Header ")

        ppg = _find_widget(window, "ppg_canvas")
        if ppg is not None:
            if ppg.width() < 1000 or ppg.height() < 200:
                main_res.errors.append(
                    f"ppg_canvas size {ppg.width()}x{ppg.height()} smaller than expected >=1000x200"
                )
        for btn_name in ("btn_patient", "btn_settings", "btn_record"):
            btn = _find_widget(window, btn_name)
            if btn is not None and btn.height() < 44:
                main_res.errors.append(f"{btn_name} height {btn.height()} < 44px touch target")

        main_res.passed = len(main_res.errors) == 0
        results.append(main_res)

        # ------------------------------------------------------------------
        # 2. PatientScreen
        # ------------------------------------------------------------------
        btn_patient = _find_widget(window, "btn_patient")
        if btn_patient is not None:
            _click(btn_patient, wait_ms=120)

        patient_res, _ = _capture_and_check_base(
            window,
            "patient_screen",
            out_dir,
            required_colors=["#226DAA", "#1EB5D7", "#D9D9D9"],
            check_ededed_canvas=True,
        )
        ps_widget = _find_widget(window, "patient_screen")
        if ps_widget is None or not ps_widget.isVisible():
            patient_res.errors.append("patient_screen is not visible after clicking btn_patient")
        else:
            ps_items: list[tuple[str, Any]] = []
            for name in (
                "patient_scroll_area",
                "btn_back",
                "btn_delete_patient",
                "btn_edit_patient",
                "btn_new_patient",
            ):
                w = _find_widget(ps_widget, name)
                if w is None or not w.isVisible():
                    patient_res.errors.append(f"PatientScreen widget {name!r} missing or not visible")
                else:
                    ps_items.append((name, _global_rect(w, window)))
            _check_window_bounds(ps_items, patient_res.errors)
            _check_no_pairwise_overlap(ps_items, patient_res.errors, context="PatientScreen ")

            scroll_area = _find_widget(ps_widget, "patient_scroll_area")
            if scroll_area is not None:
                vp_rect = _global_rect(scroll_area.viewport(), window)
                cards = _find_patient_card_rows(ps_widget)
                if not cards:
                    patient_res.warnings.append("No patient card rows visible in patient_scroll_area")
                visible_cards = [
                    c for c in cards if vp_rect.intersects(_global_rect(c, window))
                ]
                for idx in range(len(visible_cards) - 1):
                    r_cur = _global_rect(visible_cards[idx], window)
                    r_nxt = _global_rect(visible_cards[idx + 1], window)
                    if r_cur.bottom() > r_nxt.top() + 2:
                        patient_res.errors.append(
                            f"Patient cards {idx} and {idx+1} overlap vertically: "
                            f"{r_cur.getRect()} vs {r_nxt.getRect()}"
                        )
                    if r_cur.left() < vp_rect.left() - 2 or r_cur.right() > vp_rect.right() + 2:
                        patient_res.errors.append(
                            f"Patient card {idx} overflows viewport horizontally: "
                            f"{r_cur.getRect()} vs {vp_rect.getRect()}"
                        )

        patient_res.passed = len(patient_res.errors) == 0
        results.append(patient_res)

        # ------------------------------------------------------------------
        # 3. SettingsModal
        # ------------------------------------------------------------------
        btn_back = _find_widget(window, "btn_back")
        if btn_back is not None and btn_back.isVisible():
            _click(btn_back, wait_ms=100)
        btn_settings = _find_widget(window, "btn_settings")
        if btn_settings is not None:
            _click(btn_settings, wait_ms=120)

        settings_res, _ = _capture_and_check_base(
            window,
            "settings_modal",
            out_dir,
            required_colors=["#FF6161", "#90FF93", "#F0F0F0", "#D9D9D9"],
            check_ededed_canvas=False,
        )
        s_modal = _find_overlay(window, "settings_modal")
        if s_modal is None or not s_modal.isVisible():
            settings_res.errors.append("settings_modal is not visible after clicking btn_settings")
        else:
            s_scroll = _find_widget(s_modal, "settings_scroll_area")
            s_close = _find_widget(s_modal, "btn_settings_close")
            if s_close is None or not s_close.isVisible():
                settings_res.errors.append("btn_settings_close missing or hidden on settings_modal")
            close_rect = _global_rect(s_close, window) if s_close is not None else None
            if close_rect is not None:
                _check_window_bounds([("btn_settings_close", close_rect)], settings_res.errors)

            vp_rect = _global_rect(s_scroll.viewport(), window) if s_scroll is not None else _global_rect(s_modal, window)
            visible_rows: list[tuple[str, Any]] = []
            for idx in range(1, 9):
                row = _find_widget(s_modal, f"settings_row_{idx}")
                if row is None:
                    settings_res.errors.append(f"settings_row_{idx} missing")
                    continue
                r_rect = _global_rect(row, window)
                if row.isVisible() and vp_rect.intersects(r_rect):
                    visible_rows.append((f"settings_row_{idx}", r_rect))
                    # Check label vs control inside row
                    labels = [lbl for lbl in row.findChildren(QLabel) if lbl.isVisible()]
                    ctrls = [
                        c
                        for c in row.findChildren(QWidget)
                        if c.isVisible()
                        and c not in labels
                        and c.mapTo(row, c.rect().topLeft()).x() >= row.width() * 0.45
                    ]
                    if labels and ctrls:
                        l_rect = _global_rect(labels[0], window)
                        c_rect = _global_rect(ctrls[0], window)
                        _check_no_pairwise_overlap(
                            [(f"row_{idx}_label", l_rect), (f"row_{idx}_ctrl", c_rect)],
                            settings_res.errors,
                            context=f"Settings row {idx} ",
                        )
                    if close_rect is not None and r_rect.intersects(close_rect):
                        inter = r_rect.intersected(close_rect)
                        if inter.width() > 2 and inter.height() > 2:
                            settings_res.errors.append(
                                f"btn_settings_close overlaps settings_row_{idx}"
                            )

            _check_no_pairwise_overlap(visible_rows, settings_res.errors, context="SettingsModal ")

            if s_close is not None and s_close.isVisible():
                _click(s_close, wait_ms=100)

        settings_res.passed = len(settings_res.errors) == 0
        results.append(settings_res)

        # ------------------------------------------------------------------
        # 4. NewPatientDialog (centered, keyboard dismissed)
        # ------------------------------------------------------------------
        btn_patient = _find_widget(window, "btn_patient")
        if btn_patient is not None and btn_patient.isVisible():
            _click(btn_patient, wait_ms=100)
        btn_new_patient = _find_widget(window, "btn_new_patient")
        if btn_new_patient is not None:
            _click(btn_new_patient, wait_ms=120)
        _dismiss_keyboard_if_open(window)

        dlg_res, _ = _capture_and_check_base(
            window,
            "new_patient_dialog",
            out_dir,
            required_colors=["#FF7F7F", "#90FF93", "#FDFDFD", "#D9D9D9"],
            check_ededed_canvas=False,
        )
        dlg = _find_overlay(window, "new_patient_dialog")
        dlg_controls = [
            "input_patient_name",
            "input_patient_age",
            "input_patient_height",
            "input_patient_weight",
            "btn_patient_cancel",
            "btn_patient_save",
        ]
        if dlg is None or not dlg.isVisible():
            dlg_res.errors.append("new_patient_dialog is not visible after clicking btn_new_patient")
        else:
            dlg_items: list[tuple[str, Any]] = []
            for name in dlg_controls:
                w = _find_widget(dlg, name)
                if w is None or not w.isVisible():
                    dlg_res.errors.append(f"NewPatientDialog control {name!r} missing or hidden")
                else:
                    dlg_items.append((name, _global_rect(w, window)))
            _check_window_bounds(dlg_items, dlg_res.errors)
            _check_no_pairwise_overlap(dlg_items, dlg_res.errors, context="NewPatientDialog ")

        dlg_res.passed = len(dlg_res.errors) == 0
        results.append(dlg_res)

        # ------------------------------------------------------------------
        # 5. NewPatientDialog + VirtualKeyboardOverlay (non-occlusion)
        # ------------------------------------------------------------------
        if dlg is not None and dlg.isVisible():
            name_field = _find_widget(dlg, "input_patient_name")
            if name_field is not None:
                _click(name_field, wait_ms=140)

        kb_res, _ = _capture_and_check_base(
            window,
            "new_patient_keyboard",
            out_dir,
            required_colors=["#FF7F7F", "#90FF93", "#FDFDFD", "#D9D9D9"],
            check_ededed_canvas=False,
        )
        kb = _find_overlay(window, "virtual_keyboard_overlay")
        if kb is None or not kb.isVisible():
            kb_res.errors.append("virtual_keyboard_overlay did not become visible on input focus")
        else:
            kb_rect = _global_rect(kb, window)
            _check_window_bounds([("virtual_keyboard_overlay", kb_rect)], kb_res.errors)
            if kb_rect.width() < 600 or kb_rect.height() < 150:
                kb_res.errors.append(
                    f"virtual_keyboard_overlay size {kb_rect.width()}x{kb_rect.height()} too small (<600x150)"
                )

            if dlg is not None and dlg.isVisible():
                for name in dlg_controls:
                    ctrl = _find_widget(dlg, name)
                    if ctrl is None or not ctrl.isVisible():
                        kb_res.errors.append(f"{name!r} missing or hidden when keyboard open")
                        continue
                    c_rect = _global_rect(ctrl, window)
                    _check_window_bounds([(name, c_rect)], kb_res.errors)
                    if c_rect.intersects(kb_rect):
                        inter = c_rect.intersected(kb_rect)
                        kb_res.errors.append(
                            f"virtual_keyboard_overlay {kb_rect.getRect()} occludes {name} "
                            f"{c_rect.getRect()} (intersection {inter.width()}x{inter.height()})"
                        )

            key_buttons = [
                b for b in kb.findChildren(QAbstractButton) if b.isVisible()
            ]
            if len(key_buttons) < 10:
                kb_res.errors.append(f"Expected >= 10 visible keyboard key buttons, found {len(key_buttons)}")
            key_rects: list[tuple[str, Any]] = []
            for idx, btn in enumerate(key_buttons):
                kr = _global_rect(btn, window)
                if kr.width() < 28 or kr.height() < 32:
                    kb_res.errors.append(
                        f"Keyboard key {btn.text()!r} size {kr.width()}x{kr.height()} below 28x32"
                    )
                key_rects.append((btn.text() or f"key_{idx}", kr))
            _check_no_pairwise_overlap(key_rects, kb_res.errors, context="VirtualKeyboard ")

        kb_res.passed = len(kb_res.errors) == 0
        results.append(kb_res)

        all_passed = all(r.passed for r in results)
        return RubricReport(passed=all_passed, results=results)
    finally:
        if owns_window:
            try:
                window.close()
                window.deleteLater()
            except RuntimeError:
                pass
            app.processEvents()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for standalone 1280x720 screenshot rubric verification."""
    parser = argparse.ArgumentParser(
        prog="python -m tests.e2e.screenshot_rubric",
        description="Capture 1280x720 offscreen VitalSense5 screenshots and run Figma visual/geometry rubric.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "artifacts" / "screenshots",
        help="Output directory for captured 1280x720 PNG screenshots",
    )
    args = parser.parse_args(argv)
    report = run_screenshot_rubric(args.out)
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
