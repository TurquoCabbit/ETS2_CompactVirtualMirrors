import sys
from pathlib import Path

from mirrors.release_info import APP_NAME, VERSION


def main():
    if sys.version_info < (3, 11):
        print("ETS2 Configurable Mirrors requires Python 3.11 or newer. See README.md.", file=sys.stderr)
        return 1
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        if getattr(sys, "frozen", False):
            raise
        print("Install the GUI dependencies with python -m pip install -r requirements.txt.",
              file=sys.stderr)
        return 1
    from mirrors.gui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    if sys.argv[1:] == ["--version"]:
        if sys.stdout is not None:
            print(f"{APP_NAME} {VERSION}")
        return 0
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("mirrors") / "app.ico")))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
