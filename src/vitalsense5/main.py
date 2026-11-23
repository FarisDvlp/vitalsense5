"""Application bootstrap and CLI entrypoint for VitalSense5."""

from __future__ import annotations

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from vitalsense5.adapters import (
    InMemoryPatientStore,
    InMemorySettingsStore,
    MockSessionCommandHandler,
    MockVitalDataAdapter,
)
from vitalsense5.contracts import (
    PatientStorePort,
    SessionCommandPort,
    SettingsPort,
    VitalDataPort,
)
from vitalsense5.screens import MainWindow
from vitalsense5.theme import app_base_qss, load_bundled_fonts


_APP_INSTANCE: QApplication | None = None


def create_app(
    *,
    vital_port: VitalDataPort | None = None,
    patient_store: PatientStorePort | None = None,
    settings_store: SettingsPort | None = None,
    command_handler: SessionCommandPort | None = None,
    kiosk: bool = False,
    tick_ms: int = 33,
) -> MainWindow:
    """Create and wire the MainWindow with injected or default mock adapters."""
    global _APP_INSTANCE
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        _APP_INSTANCE = app
    elif isinstance(app, QApplication):
        _APP_INSTANCE = app

    load_bundled_fonts()
    if isinstance(app, QApplication):
        app.setStyleSheet(app_base_qss())

    resolved_vital = vital_port if vital_port is not None else MockVitalDataAdapter()
    resolved_patients = (
        patient_store if patient_store is not None else InMemoryPatientStore()
    )
    resolved_settings = (
        settings_store if settings_store is not None else InMemorySettingsStore()
    )
    resolved_commands = (
        command_handler
        if command_handler is not None
        else MockSessionCommandHandler()
    )

    return MainWindow(
        vital_port=resolved_vital,
        patient_store=resolved_patients,
        settings_store=resolved_settings,
        command_handler=resolved_commands,
        kiosk=kiosk,
        tick_ms=tick_ms,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vitalsense5",
        description="VitalSense5 PyQt6 Frontend Monitor",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--windowed",
        action="store_true",
        help="Launch in fixed 1280x720 desktop test window (default)",
    )
    mode_group.add_argument(
        "--kiosk",
        action="store_true",
        help="Launch in frameless fullscreen kiosk mode for Raspberry Pi 5",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Use built-in mock vital data and in-memory adapters (default)",
    )
    parser.add_argument(
        "--tick-ms",
        type=int,
        default=33,
        help="UI polling interval in milliseconds (default: 33)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``python -m vitalsense5`` and ``vitalsense5`` script."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    window = create_app(kiosk=bool(args.kiosk), tick_ms=int(args.tick_ms))
    if not args.kiosk:
        window.show()

    return int(app.exec())


__all__ = ["create_app", "main"]
