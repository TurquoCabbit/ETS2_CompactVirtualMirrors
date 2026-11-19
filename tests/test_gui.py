from dataclasses import replace
from fractions import Fraction
import os
import sys
from zipfile import ZipFile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QLineEdit, QMessageBox, QPushButton

import main
from mirrors import config
from mirrors.builder import MOD_NAME, build
from mirrors.gui import MainWindow
from mirrors.hud import inspect, transform
from mirrors.model import DEFAULT, HANDLES, Mirror

LEFT = Qt.MouseButton.LeftButton
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(application, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    paths = {"game": None, "source": None, "output": None, "mod": None}
    monkeypatch.setattr("mirrors.gui.directory_defaults", lambda: paths)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    path = tmp_path / "config.ini"
    config.save(path, DEFAULT)
    window = MainWindow(path, settings)
    window.show()
    application.processEvents()
    yield window
    window.saved = window.model
    window.close()
    application.processEvents()
    window.deleteLater()


def _drag(preview, point, target):
    widget = preview.viewport()
    QTest.mousePress(widget, LEFT, pos=point)
    QTest.mouseMove(widget, target)
    QTest.mouseRelease(widget, LEFT, pos=target)


def _move_scene(preview, start, dx, dy):
    return preview.mapFromScene(preview.mapToScene(start) + QPointF(dx, dy))


@pytest.mark.parametrize("window_size", [(800, 510), (1300, 820)])
def test_preview_to_config_drag_and_scale(window, application, window_size):
    window.resize(*window_size)
    application.processEvents()
    preview = window.preview
    assert window.model == DEFAULT
    left = DEFAULT.left
    start = preview.mapFromScene(QPointF(left.x + left.width / 2, left.y + left.height / 2))
    target = _move_scene(preview, start, 65, 54)
    delta = preview.mapToScene(target) - preview.mapToScene(start)
    _drag(preview, start, target)
    assert window.model.left == replace(left, x=left.x + round(delta.x()), y=left.y + round(delta.y()))
    assert window.model.right == DEFAULT.right
    assert window.inputs["x"].value() == window.model.left.x
    assert window.inputs["y"].value() == window.model.left.y
    assert window.dirty
    assert window.save_config()
    assert config.load(window.path) == window.model
    scale = preview.transform().m11()
    window.resize(1031, 675)
    application.processEvents()
    assert preview.transform().m11() != scale
    assert config.load(window.path) == window.model
    assert not window.dirty


@pytest.mark.parametrize("handle", HANDLES)
def test_all_resize_handles_drive_only_selected_mirror(window, handle):
    preview = window.preview
    h, v = HANDLES[handle]
    start = preview.handles()[handle]
    target = _move_scene(preview, start, -h * 30, -v * 42)
    delta = preview.mapToScene(target) - preview.mapToScene(start)
    _drag(preview, start, target)
    assert window.model.left.width == DEFAULT.left.width + h * round(delta.x())
    assert window.model.left.height == DEFAULT.left.height + v * round(delta.y())
    assert window.model.right == DEFAULT.right
    assert window.inputs["width"].value() == window.model.left.width
    assert window.inputs["height"].value() == window.model.left.height


def test_right_selection_numeric_typing_ratio_and_keyboard(window):
    preview = window.preview
    right = DEFAULT.right
    center = preview.mapFromScene(QPointF(right.x + 80, right.y + 100))
    QTest.mouseClick(preview.viewport(), LEFT, pos=center)
    assert window.side == "right"
    assert window.selector.currentIndex() == 1
    QTest.keyClick(preview, Qt.Key.Key_Left)
    QTest.keyClick(preview, Qt.Key.Key_Down, SHIFT)
    assert window.model.right == replace(right, x=right.x - 1, y=right.y + 10)
    editor = window.inputs["x"]
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, CTRL)
    QTest.keyClicks(editor, "1200")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert window.model.right.x == 1200
    assert preview.layout_model == window.model
    window.aspect.setChecked(True)
    window.inputs["width"].setValue(80)
    assert window.model.right.height == 128
    assert window.model.left == DEFAULT.left


@pytest.mark.parametrize("side", ["left", "right"])
def test_reset_button_restores_native_mirror(window, source, tmp_path, side):
    window.directories["source"] = str(source if side == "left" else source.parent)
    window.select(side)
    window.inputs["x"].setValue(100)
    window.aspect.setChecked(True)
    opposite = "right" if side == "left" else "left"
    before = window.model

    reset = next(button for button in window.findChildren(QPushButton)
                 if button.text() == "Reset selected mirror")
    reset.click()

    assert window.model.mirror(side) == Mirror(20, 126, 267, 341, 8)
    assert window.model.mirror(opposite) == before.mirror(opposite)
    assert (window.model.width, window.model.height) == (before.width, before.height)
    assert window.preview.layout_model == window.model
    assert window.inputs["frame_padding"].value() == 8
    assert window.ratios[side] == Fraction(267, 341)
    assert window.dirty and window.save_config()
    restored = config.load(window.path)
    assert restored == window.model
    assert restored.game_defaults == {side}

    artifact = build(restored, source, tmp_path / "output")
    with ZipFile(artifact) as archive:
        assert archive.read(f"ui/hud_{side}.sii") == (source / f"hud_{side}.sii").read_bytes()
        assert archive.read(f"ui/hud_{opposite}.sii") != (source / f"hud_{opposite}.sii").read_bytes()

    window.inputs["x"].setValue(21)
    assert window.save_config()
    assert config.load(window.path).game_defaults == set()


@pytest.mark.parametrize("source_state", ["missing", "invalid"])
def test_reset_failure_keeps_current_layout(window, source, source_state, monkeypatch):
    if source_state == "invalid":
        window.directories["source"] = str(source)
        (source / "hud_left.sii").write_text("Invalid HUD")
    window.inputs["x"].setValue(60)
    before = window.model
    errors = []
    monkeypatch.setattr(window, "_error", lambda title, message: errors.append((title, message)))

    window.reset_mirror()

    assert window.model == before and window.dirty
    assert errors[0][0] == "Could not reset mirror"


@pytest.mark.parametrize(("side", "handle", "direction"), [
    ("left", "e", 1), ("right", "w", -1),
])
def test_preview_padding_updates_selected_frame_config_and_archive(
        window, tmp_path, source, side, handle, direction):
    preview = window.preview
    window.select(side)
    original = DEFAULT.mirror(side)
    opposite = "right" if side == "left" else "left"
    mode = window.findChild(QCheckBox, "editPadding")
    mode.click()
    assert set(preview.handles()) == {"n", "e", "s", "w"}

    start = preview.handles()[handle]
    target = _move_scene(preview, start, direction * 35, 0)
    delta = round((preview.mapToScene(target) - preview.mapToScene(start)).x())
    _drag(preview, start, target)
    padded = replace(original, frame_padding=original.frame_padding + direction * delta)
    assert window.model.mirror(side) == padded
    assert window.model.mirror(opposite) == DEFAULT.mirror(opposite)
    assert window.inputs["frame_padding"].value() == padded.frame_padding
    assert window.save_config()
    assert config.load(window.path).mirror(side) == padded

    artifact = build(window.model, source, tmp_path / "output")
    with ZipFile(artifact) as archive:
        bounds, _, groups = inspect(archive.read(f"ui/hud_{side}.sii").decode(), side)
        frame = transform(padded.frame(window.model.width, window.model.height),
                          window.model, bounds)
        assert all(border.bounds() == frame for _, border, _ in groups)

    start = preview.handles()[handle]
    _drag(preview, start, _move_scene(preview, start, direction * -80, 0))
    assert window.model.mirror(side) == replace(original, frame_padding=0)
    assert window.inputs["frame_padding"].value() == 0
    start = preview.handles()[handle]
    window.inputs["frame_padding"].setValue(14)
    assert (preview.handles()[handle].x() - start.x()) * direction > 0
    mode.click()
    assert set(preview.handles()) == set(HANDLES)


def test_reload_prompts_with_cancel_discard_and_save(window, monkeypatch):
    window.inputs["x"].setValue(40)
    buttons = QMessageBox.StandardButton
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: buttons.Cancel)
    window.reload_config()
    assert window.model.left.x == 40 and window.dirty
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: buttons.Discard)
    window.reload_config()
    assert window.model == DEFAULT and not window.dirty
    window.inputs["x"].setValue(50)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: buttons.Save)
    window.reload_config()
    assert config.load(window.path).left.x == 50 and not window.dirty


def test_invalid_reload_keeps_current_layout(window):
    window.path.write_text("[screen]\nwidth = 0")
    window.reload_config()
    assert window.model == DEFAULT
    assert window.path.read_text() == "[screen]\nwidth = 0"


def test_screen_size_and_minimum_controls(window, monkeypatch):
    monkeypatch.setattr(window, "_size_dialog", lambda *args: (600, 450))
    window.change_screen()
    assert window.model == DEFAULT
    monkeypatch.setattr(window, "_size_dialog", lambda *args: (2000, 1180))
    window.change_screen()
    assert (window.model.width, window.model.height) == (2000, 1180)
    assert window.model.right == DEFAULT.right
    monkeypatch.setattr(window, "_size_dialog", lambda *args: (80, 100))
    window.change_minimum()
    start = window.preview.handles()["se"]
    _drag(window.preview, start, start - QPoint(100, 100))
    assert (window.model.left.width, window.model.left.height) == (80, 100)


def test_screenshot_is_preview_only(window, tmp_path):
    image_path = tmp_path / "screen.png"
    image = QImage(160, 90, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(image_path))
    window._load_image(str(image_path))
    assert not window.preview.image.isNull()
    assert window.model == DEFAULT and not window.dirty
    window.clear_image()
    assert window.preview.image.isNull()
    assert not window.settings.contains("preview/screenshot")


def _wait_for_work(window):
    for _ in range(300):
        if window.operation is None:
            break
        QTest.qWait(10)
    assert window.operation is None


def test_gui_build_and_install_confirm_replacement(window, source, tmp_path, monkeypatch):
    output = tmp_path / "output"
    mod = tmp_path / "mod"
    window.directories.update(source=str(source), output=str(output), mod=str(mod))
    window.inputs["x"].setValue(80)
    assert not window.install_button.isEnabled()
    window.build_mod()
    _wait_for_work(window)
    assert window.artifact == output / MOD_NAME
    assert window.artifact.is_file()
    assert window.install_button.isEnabled()
    assert "Built" in window.build_status.text()
    assert config.load(window.path) == DEFAULT
    window.install_mod()
    _wait_for_work(window)
    target = mod / MOD_NAME
    assert target.read_bytes() == window.artifact.read_bytes()
    assert "Activate" in window.build_status.text()
    target.write_bytes(b"existing")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.install_mod()
    assert target.read_bytes() == b"existing"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.install_mod()
    _wait_for_work(window)
    assert target.read_bytes() == window.artifact.read_bytes()


def test_setup_and_changes_control_which_build_can_be_installed(window, source, tmp_path):
    assert not window.build_button.isEnabled()
    window._set_directories({"source": str(tmp_path), "output": str(tmp_path / "output"),
                             "mod": str(tmp_path / "mod")})
    assert not window.build_button.isEnabled()
    window._set_directories({"source": str(source)})
    assert window.build_button.isEnabled()
    window.build_mod()
    _wait_for_work(window)
    assert window.install_button.isEnabled()
    original_x = window.inputs["x"].value()
    window.inputs["x"].setValue(original_x + 1)
    window.inputs["x"].setValue(original_x)
    assert not window.install_button.isEnabled()
    window.build_mod()
    _wait_for_work(window)
    assert window.install_button.isEnabled()
    window._set_directories({"output": str(tmp_path / "another output")})
    assert not window.install_button.isEnabled()


def test_failed_rebuild_leaves_the_old_archive_uninstallable(window, source, tmp_path, monkeypatch):
    window._set_directories({"source": str(source), "output": str(tmp_path / "output"),
                             "mod": str(tmp_path / "mod")})
    window.build_mod()
    _wait_for_work(window)
    contents = window.artifact.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("Disk write failed")

    monkeypatch.setattr("mirrors.gui.build", fail)
    window.build_mod()
    _wait_for_work(window)
    assert not window.install_button.isEnabled()
    assert window.artifact.read_bytes() == contents
    assert "Disk write failed" in window.build_status.text()


def test_compact_and_save_as_create_an_independent_layout(window, legacy_ini, tmp_path):
    assert window._load(legacy_ini)
    before = legacy_ini.read_bytes()
    window.apply_compact()
    destination = tmp_path / "layouts" / "compact.ini"
    assert window._save_config(destination)
    assert window.path == destination
    assert not window.dirty
    assert config.load(destination) == config.load(config.COMPACT_PRESET)
    assert "PathWithCase" in destination.read_text(encoding="utf-8")
    assert legacy_ini.read_bytes() == before


def test_editor_launches_with_defaults_without_a_setup_dialog(application, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    dialogs = []
    windows = []

    def create_window():
        window = MainWindow(settings=settings)
        windows.append(window)
        return window

    def record_dialog(dialog):
        dialogs.append(dialog.windowTitle())
        return QDialog.DialogCode.Rejected

    def run_event_loop():
        application.processEvents()
        window, = windows
        assert window.isVisible()
        assert window.model == DEFAULT
        assert not window.build_button.isEnabled()
        assert not dialogs
        return 0

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr("mirrors.gui.editor_directory", lambda: tmp_path)
    monkeypatch.setattr("mirrors.gui.directory_defaults", lambda: dict(
        game=None, source=None, output=tmp_path / "output", mod=None))
    monkeypatch.setattr("mirrors.gui.MainWindow", create_window)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", lambda argv: application)
    monkeypatch.setattr(application, "exec", run_event_loop)
    monkeypatch.setattr(QDialog, "exec", record_dialog)
    try:
        assert main.main() == 0
    finally:
        for window in windows:
            window.close()


@pytest.mark.parametrize("save", [True, False])
def test_directories_can_be_configured_from_the_editor(window, source, tmp_path, save):
    choices = {"game": str(tmp_path / "ETS2"), "source": str(source),
               "output": str(tmp_path / "output"), "mod": str(tmp_path / "mod")}
    before = dict(window.directories)
    seen = []

    def answer():
        dialog = QApplication.activeModalWidget()
        entries = dialog.findChildren(QLineEdit)
        seen.append((dialog.windowTitle(), len(entries)))
        for entry, value in zip(entries, choices.values()):
            entry.setText(value)
        buttons = dialog.findChild(QDialogButtonBox)
        button = QDialogButtonBox.StandardButton.Ok if save else QDialogButtonBox.StandardButton.Cancel
        buttons.button(button).click()

    QTimer.singleShot(0, answer)
    window.change_directories()
    assert seen == [("Directories", 4)]
    assert window.directories == (choices if save else before)
    for key, value in choices.items():
        assert window.settings.value(f"paths/{key}") == (value if save else None)
