"""Application start-up: paths, single instance, Qt, settings, controller."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback

from sayso import APP_NAME, __version__

log = logging.getLogger(__name__)


def run(args: argparse.Namespace) -> int:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from sayso.core.config import load_settings
    from sayso.core.history import History
    from sayso.core.logging_setup import setup_logging
    from sayso.core.paths import resolve_paths
    from sayso.ui import icons, theme
    from sayso.ui.controller import Controller
    from sayso.winsys import single_instance
    from sayso.winsys.credentials import CredentialStore

    paths = resolve_paths().ensure()
    setup_logging(paths.log_file)
    log.info("%s %s starting (portable=%s)", APP_NAME, __version__, paths.portable)

    if not single_instance.acquire("Local\\Sayso"):
        single_instance.signal_show()
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icons.icon())
    theme.apply(app)

    controller = None
    try:
        loaded = load_settings(paths.settings_file, paths.policy_file if paths.policy_file.exists() else None)
        if getattr(args, "offline", False):
            loaded.settings.privacy.offline_only = True
        creds = CredentialStore(paths)
        history = History(paths.history_db, loaded.settings.privacy.history_enabled,
                          loaded.settings.privacy.history_retention_days)
        controller = Controller(app, paths, loaded, creds, history)

        class Bridge(QObject):
            show = Signal()

        bridge = Bridge()
        bridge.show.connect(controller.show_settings)
        stop_listener = single_instance.wait_show(bridge.show.emit)
        controller.start()
        code = app.exec()
        stop_listener()
        return code
    except Exception as exc:
        log.exception("fatal error")
        QMessageBox.critical(None, APP_NAME, f"Sayso could not start: {exc}\n\nDetails are in {paths.log_file}")
        traceback.print_exc()
        return 1
    finally:
        if controller is not None:
            controller.shutdown()
