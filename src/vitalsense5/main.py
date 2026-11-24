"""Application bootstrap and CLI entrypoint for VitalSense5."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from PyQt6.QtWidgets import QApplication

from vitalsense5.adapters import (
    InMemoryPatientStore,
    InMemorySettingsStore,
    MockSessionCommandHandler,
    MockVitalDataAdapter,
)
from vitalsense5.backend import SerialVitalAdapter
from vitalsense5.contracts import (
    PatientStorePort,
    SessionCommandPort,
    SettingsPort,
    VitalDataPort,
)
from vitalsense5.screens import MainWindow
from vitalsense5.theme import app_base_qss, load_bundled_fonts

logger = logging.getLogger(__name__)
_APP_INSTANCE: QApplication | None = None


def _resolve_vital_adapter(
    *,
    patient_store: PatientStorePort,
    use_serial: bool | None = None,
    serial_port: str | None = None,
    baudrate: int | None = None,
) -> VitalDataPort:
    """Select SerialVitalAdapter when requested/available, else fall back to MockVitalDataAdapter."""
    resolved_port = serial_port or os.environ.get("VITALSENSE5_SERIAL_PORT", "/dev/ttyAMA0")
    resolved_baud = (
        baudrate
        if baudrate is not None
        else int(os.environ.get("VITALSENSE5_BAUDRATE", "460800"))
    )

    if use_serial is None:
        env_flag = os.environ.get("VITALSENSE5_SERIAL", "").strip().lower()
        if env_flag in ("1", "true", "yes", "on"):
            use_serial = True
        elif env_flag in ("0", "false", "no", "off"):
            use_serial = False

    should_try_serial = use_serial is True or (
        use_serial is None and os.path.exists(resolved_port)
    )
    if should_try_serial:
        if not os.path.exists(resolved_port):
            logger.warning(
                "Serial port %s not found; falling back to MockVitalDataAdapter.",
                resolved_port,
            )
            return MockVitalDataAdapter()
        try:
            return SerialVitalAdapter(
                port=resolved_port,
                baudrate=resolved_baud,
                patient_store=patient_store,
            )
        except Exception as exc:
            logger.warning(
                "Failed to initialize SerialVitalAdapter on %s (%s); falling back to MockVitalDataAdapter.",
                resolved_port,
                exc,
            )

    return MockVitalDataAdapter()


def create_app(
    *,
    vital_port: VitalDataPort | None = None,
    patient_store: PatientStorePort | None = None,
    settings_store: SettingsPort | None = None,
    command_handler: SessionCommandPort | None = None,
    kiosk: bool = False,
    tick_ms: int = 33,
    use_serial: bool | None = None,
    serial_port: str | None = None,
    baudrate: int | None = None,
) -> MainWindow:
    """Create and wire the MainWindow with injected or default/serial adapters."""
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

    resolved_patients = (
        patient_store if patient_store is not None else InMemoryPatientStore()
    )
    resolved_vital = (
        vital_port
        if vital_port is not None
        else _resolve_vital_adapter(
            patient_store=resolved_patients,
            use_serial=use_serial,
            serial_port=serial_port,
            baudrate=baudrate,
        )
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
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--mock",
        action="store_true",
        help="Use built-in mock vital data adapter",
    )
    source_group.add_argument(
        "--serial",
        action="store_true",
        help="Read 460800-baud NDJSON telemetry from ESP32-S3 over UART (falls back to mock if port is missing)",
    )
    parser.add_argument(
        "--serial-port",
        type=str,
        default=None,
        help="UART device path (default: $VITALSENSE5_SERIAL_PORT or /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=None,
        help="UART baud rate (default: $VITALSENSE5_BAUDRATE or 460800)",
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

    use_serial: bool | None = None
    if args.serial:
        use_serial = True
    elif args.mock:
        use_serial = False

    window = create_app(
        kiosk=bool(args.kiosk),
        tick_ms=int(args.tick_ms),
        use_serial=use_serial,
        serial_port=args.serial_port,
        baudrate=args.baudrate,
    )
    if not args.kiosk:
        window.show()

    return int(app.exec())


__all__ = ["create_app", "main"]
