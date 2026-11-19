from dataclasses import replace
from fractions import Fraction
from functools import partial
from os.path import expanduser
from pathlib import Path
import zipfile

from PySide6.QtCore import QSettings, QSignalBlocker, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QImage, QImageReader, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from . import config
from .builder import MOD_NAME, build, install, load_game_mirror, validate_source
from .model import DEFAULT, FIELDS, HANDLES, MAX_VALUE, SIDES, edit, move, resize, validate
from .preferences import DIRECTORIES, directory_defaults, editor_directory
from .preview import MirrorPreview
from .release_info import APP_NAME, AUTHOR, EXTRACTOR_URL, PROJECT_URL, VERSION

BUTTON = QMessageBox.StandardButton
OK_CANCEL = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel


class Operation(QThread):
    progress = Signal(str)
    success = Signal(object)
    failed = Signal(str)

    def __init__(self, work, parent):
        super().__init__(parent)
        self.work = work

    def run(self):
        try:
            result = self.work(progress=self.progress.emit)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self.failed.emit(str(exc))
        else:
            self.success.emit(result)


def make_spin(low=0, value=None):
    spin = QSpinBox()
    spin.setRange(low, MAX_VALUE)
    spin.setAccelerated(True)
    if value is not None:
        spin.setValue(value)
    return spin


def dialog_buttons(dialog, row):
    buttons = QDialogButtonBox(OK_CANCEL, parent=dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    row.addRow(buttons)


class MainWindow(QMainWindow):
    def __init__(self, path=None, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings(APP_NAME, APP_NAME)
        self.path = Path(path) if path is not None else editor_directory() / "config.ini"
        self.model = self.saved = DEFAULT
        self.side = "left"
        self.ratios = {}
        self.minimum = tuple(self._minimum(axis) for axis in ("width", "height"))
        self.operation = None
        self.artifact = None
        self.build_inputs = None
        self.screenshot = ""

        defaults = directory_defaults()
        self.directories = {
            key: self.settings.value(f"paths/{key}", str(path) if path else "", type=str)
            for key, path in defaults.items()
        }
        self.source_error = self._source_error(self._directory("source"))
        self._make_interface()
        self._make_menus()
        self.resize(1080, 690)
        if self.path.exists():
            self._load(self.path)
        else:
            self.statusBar().showMessage(f"Editing defaults. Save to create {self.path.name}.")
        screenshot = self.settings.value("preview/screenshot", "", type=str)
        if screenshot:
            self._load_image(screenshot, report=False)
        self._refresh()

    def _minimum(self, axis):
        return max(1, min(MAX_VALUE, self.settings.value(f"editor/minimum_{axis}", 1, type=int)))

    def _make_interface(self):
        root = QWidget()
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(12)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        column.addWidget(splitter, 1)
        preview_panel = QWidget()
        preview_column = QVBoxLayout(preview_panel)
        preview_column.setContentsMargins(0, 0, 8, 0)
        heading = QHBoxLayout()
        self.canvas_label = QLabel()
        self.canvas_label.setStyleSheet("font-weight: 600;")
        heading.addWidget(self.canvas_label, 1)
        self._button(heading, "Screen size…", self.change_screen)
        self._button(heading, "Screenshot…", self.choose_image)
        preview_column.addLayout(heading)
        self.preview = MirrorPreview(self.model)
        self.preview.selected.connect(self.select)
        self.preview.edited.connect(self._preview_edit)
        self.preview.nudged.connect(self._nudge)
        preview_column.addWidget(self.preview, 1)
        splitter.addWidget(preview_panel)

        panel = QWidget()
        panels = QVBoxLayout(panel)
        panels.setContentsMargins(4, 0, 0, 0)
        controls = QGroupBox("Mirror settings")
        form = QFormLayout(controls)
        self.selector = QComboBox()
        self.selector.addItems(["Left mirror", "Right mirror"])
        self.selector.currentIndexChanged.connect(lambda index: self.select(SIDES[index]))
        form.addRow("&Mirror", self.selector)
        self.inputs = {}
        labels = {"x": "&X", "y": "&Y", "width": "&Width", "height": "&Height",
                  "frame_padding": "Frame &padding"}
        for name in FIELDS:
            spin = make_spin()
            spin.setObjectName(name)
            spin.setAccessibleName(labels[name].replace("&", ""))
            spin.setToolTip("Uniform padding in virtual screen units. Zero removes the extra border."
                            if name == "frame_padding" else "Virtual screen units.")
            spin.valueChanged.connect(partial(self._numeric_edit, name))
            self.inputs[name] = spin
            form.addRow(labels[name], spin)
        padding_mode = QCheckBox("Edit padding in preview")
        padding_mode.setObjectName("editPadding")
        padding_mode.setToolTip("Switch to the amber frame handles. Drag outward to add padding "
                                "or inward to reduce it. The frame is clipped at the screen edge.")
        padding_mode.toggled.connect(self.preview.set_padding_mode)
        form.addRow(padding_mode)
        self.aspect = QCheckBox("Lock aspect ratio")
        self.aspect.toggled.connect(self._toggle_ratio)
        form.addRow(self.aspect)
        self.snap = QCheckBox("Snap to screen edges")
        self.snap.setChecked(self.settings.value("editor/snap", False, type=bool))
        self.snap.setToolTip("Snap within 8 virtual units while dragging or resizing.")
        self.snap.toggled.connect(lambda enabled: self.settings.setValue("editor/snap", enabled))
        form.addRow(self.snap)
        reset = QPushButton("Reset selected mirror")
        reset.setToolTip("Restore the selected mirror's original ETS2 presets from the extracted HUD.")
        reset.clicked.connect(self.reset_mirror)
        form.addRow(reset)
        panels.addWidget(controls)
        self._button(panels, "Apply Compact preset", self.apply_compact)
        panels.addStretch(1)
        inspector = QScrollArea()
        inspector.setWidgetResizable(True)
        inspector.setFrameShape(QScrollArea.Shape.NoFrame)
        inspector.setWidget(panel)
        inspector.setMinimumWidth(250)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([765, 255])

        actions = QHBoxLayout()
        self._button(actions, "Open Config…", self.open_config)
        self._button(actions, "Save Config", self.save_config)
        actions.addStretch(1)
        self.setup_button = self._button(actions, "Set Up HUD Files…", self.setup_hud)
        self.build_button = self._button(actions, "Build Mod", self.build_mod)
        self.build_button.setStyleSheet("font-weight: 600;")
        self.install_button = self._button(actions, "Install Mod", self.install_mod)
        column.addLayout(actions)
        self.build_status = QLabel()
        self.build_status.setTextFormat(Qt.TextFormat.PlainText)
        self.build_status.setWordWrap(True)
        self.build_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.build_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.progress.setFixedWidth(95)
        self.statusBar().addPermanentWidget(self.progress)
        self.progress.hide()

    def _button(self, row, title, callback):
        button = QPushButton(title)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def _action(self, menu, title, callback, shortcut=None):
        action = QAction(title, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def _make_menus(self):
        file = self.menuBar().addMenu("&File")
        self._action(file, "&Open Config…", self.open_config, QKeySequence.StandardKey.Open)
        self._action(file, "&Save Config", self.save_config, QKeySequence.StandardKey.Save)
        self._action(file, "Save Config &As…", self.save_config_as, QKeySequence.StandardKey.SaveAs)
        self._action(file, "&Reload Config", self.reload_config, "Ctrl+R")
        file.addSeparator()
        self._action(file, "E&xit", self.close, QKeySequence.StandardKey.Quit)
        edit_menu = self.menuBar().addMenu("&Edit")
        self._action(edit_menu, "Reset Selected Mirror", self.reset_mirror)
        self._action(edit_menu, "Reset All to Defaults", self.reset_all)
        self._action(edit_menu, "Apply Compact Preset", self.apply_compact)
        self._action(edit_menu, "Minimum Mirror Size…", self.change_minimum)
        view = self.menuBar().addMenu("&View")
        self._action(view, "Screen Size…", self.change_screen)
        self._action(view, "Choose Screenshot…", self.choose_image)
        self.clear_image_action = self._action(view, "Clear Screenshot", self.clear_image)
        tools = self.menuBar().addMenu("&Tools")
        self.setup_action = self._action(tools, "Set Up HUD Files…", self.setup_hud)
        self._action(tools, "Directories…", self.change_directories)
        self.build_action = self._action(tools, "&Build Mod", self.build_mod)
        self.install_action = self._action(tools, "&Install Mod", self.install_mod)
        self.output_action = self._action(tools, "Open Output Folder", self.open_output)
        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Editor and Mod Help", self.show_help)
        self._action(help_menu, "&About", self.show_about)

    def _refresh(self):
        mirror = self.model.mirror(self.side)
        self.preview.set_layout(self.model, self.side)
        self.canvas_label.setText(f"Screen preview  ·  {self.model.width} × {self.model.height}")
        with QSignalBlocker(self.selector):
            self.selector.setCurrentIndex(SIDES.index(self.side))
        with QSignalBlocker(self.aspect):
            self.aspect.setChecked(self.side in self.ratios)
        limits = {
            "x": (0, self.model.width - mirror.width),
            "y": (0, self.model.height - mirror.height),
            "width": (self.minimum[0], self.model.width - mirror.x),
            "height": (self.minimum[1], self.model.height - mirror.y),
            "frame_padding": (0, MAX_VALUE),
        }
        for field, spin in self.inputs.items():
            with QSignalBlocker(spin):
                low, high = limits[field]
                # An existing file may predate the user's minimum-size preference.
                spin.setRange(min(low, getattr(mirror, field)), high)
                # Keep the current text editor buffer when its value already matches.
                if spin.value() != getattr(mirror, field):
                    spin.setValue(getattr(mirror, field))
        self.setWindowTitle(f"{self.path.name}{' *' if self.dirty else ''} — {APP_NAME}")
        self.clear_image_action.setEnabled(bool(self.screenshot))
        self._refresh_operation_controls()

    @property
    def dirty(self):
        return self.model != self.saved

    def select(self, side):
        self.side = side
        self._refresh()

    def _set_mirror(self, side, mirror):
        self.model = self.model.with_mirror(side, mirror)
        self._refresh()

    def _effective_minimum(self, mirror):
        return min(self.minimum[0], mirror.width), min(self.minimum[1], mirror.height)

    def _numeric_edit(self, field, value):
        mirror = self.model.mirror(self.side)
        updated = edit(mirror, self.model, field, value, self._effective_minimum(mirror),
                       self.ratios.get(self.side))
        self._set_mirror(self.side, updated)

    def _preview_edit(self, side, handle, original, dx, dy):
        if handle == "move":
            updated = move(original, self.model, original.x + dx, original.y + dy,
                           self.snap.isChecked())
        elif handle.startswith("padding:"):
            horizontal, vertical = HANDLES[handle.removeprefix("padding:")]
            padding = original.frame_padding + horizontal * dx + vertical * dy
            updated = edit(original, self.model, "frame_padding", padding, self.minimum, None)
        else:
            updated = resize(original, self.model, handle, dx, dy,
                             self._effective_minimum(original),
                             self.ratios.get(side), self.snap.isChecked())
        self._set_mirror(side, updated)

    def _nudge(self, dx, dy):
        mirror = self.model.mirror(self.side)
        self._set_mirror(self.side, move(mirror, self.model, mirror.x + dx, mirror.y + dy))

    def _capture_ratio(self, side):
        mirror = self.model.mirror(side)
        self.ratios[side] = Fraction(mirror.width, mirror.height)

    def _toggle_ratio(self, enabled):
        self.settings.setValue(f"editor/lock_{self.side}", enabled)
        if enabled:
            self._capture_ratio(self.side)
        else:
            self.ratios.pop(self.side, None)

    def _load_ratios(self):
        self.ratios.clear()
        for side in SIDES:
            if self.settings.value(f"editor/lock_{side}", False, type=bool):
                self._capture_ratio(side)

    def reset_mirror(self):
        source = self._directory("source")
        if source is None:
            self._error("Could not reset mirror", "Set the extracted HUD source in Directories.")
            return
        try:
            mirror = load_game_mirror(source, self.side, self.model)
        except (OSError, ValueError) as exc:
            self._error("Could not reset mirror", str(exc))
            return
        self.model = self.model.with_mirror(self.side, mirror, use_game_defaults=True)
        if self.side in self.ratios:
            self._capture_ratio(self.side)
        self._refresh()
        self.statusBar().showMessage(
            f"Restored original ETS2 settings for the {self.side} mirror. Rebuild and install to apply.")

    def reset_all(self):
        if not self._discard_allowed():
            return
        self.model = DEFAULT
        self._load_ratios()
        self._refresh()
        self.statusBar().showMessage("Default canvas and mirror settings restored.")

    def apply_compact(self):
        try:
            compact = config.load(config.COMPACT_PRESET)
        except ValueError as exc:
            self._error("Could not load Compact preset", str(exc))
            return
        if self.model != compact and self._discard_allowed():
            self.model = compact
            self._load_ratios()
            self._refresh()
            self.statusBar().showMessage("Applied Compact preset. Save or build to use it.")

    def _discard_allowed(self):
        if not self.dirty:
            return True
        choice = QMessageBox.warning(
            self, "Unsaved changes", f"Save changes to {self.path.name}?",
            BUTTON.Save | BUTTON.Discard | BUTTON.Cancel, BUTTON.Save)
        return choice == BUTTON.Discard or (choice == BUTTON.Save and self.save_config())

    def _load(self, path):
        try:
            model = config.load(path)
        except ValueError as exc:
            self._error("Could not load configuration", str(exc))
            return False
        self.path = path
        self.model = self.saved = model
        self._load_ratios()
        self._refresh()
        self.statusBar().showMessage(f"Loaded {path}")
        return True

    def open_config(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open configuration", str(self.path.parent), "INI files (*.ini);;All files (*)")
        if filename and self._discard_allowed():
            self._load(Path(filename))

    def reload_config(self):
        if self._discard_allowed():
            self._load(self.path)

    def save_config(self):
        return self._save_config(self.path)

    def save_config_as(self):
        dialog = QFileDialog(self, "Save configuration as", str(self.path.parent), "INI files (*.ini)")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("ini")
        dialog.selectFile(self.path.name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_config(Path(dialog.selectedFiles()[0]))

    def _save_config(self, path):
        replace_invalid = False
        if path.exists():
            try:
                config.load(path)
            except ValueError as exc:
                replace_invalid = QMessageBox.question(
                    self, "Replace invalid configuration?",
                    f"{exc}\n\nBack up the existing file and replace its layout?",
                    BUTTON.Yes | BUTTON.No, BUTTON.No) == BUTTON.Yes
                if not replace_invalid:
                    return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            config.save(path, self.model, replace_invalid=replace_invalid, template=self.path)
        except (OSError, ValueError) as exc:
            self._error("Could not save configuration", str(exc))
            return False
        self.path = path
        self.saved = self.model
        self._refresh()
        self.statusBar().showMessage(f"Saved {self.path}")
        return True

    def _size_dialog(self, title, values):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        width, height = (make_spin(1, value) for value in values)
        form.addRow("&Width", width)
        form.addRow("&Height", height)
        dialog_buttons(dialog, form)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return width.value(), height.value()
        return None

    def change_screen(self):
        size = self._size_dialog("Virtual screen size", (self.model.width, self.model.height))
        if size:
            candidate = replace(self.model, width=size[0], height=size[1])
            try:
                validate(candidate)
            except ValueError as exc:
                self._error("Screen size does not fit the current mirrors", str(exc))
            else:
                self.model = candidate
                self._refresh()

    def change_minimum(self):
        size = self._size_dialog("Minimum mirror size", self.minimum)
        if size:
            try:
                validate(self.model, size)
            except ValueError as exc:
                self._error("Minimum size exceeds a current mirror", str(exc))
                return
            self.minimum = size
            for axis, value in zip(("width", "height"), size):
                self.settings.setValue(f"editor/minimum_{axis}", value)
            self._refresh()

    def choose_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose preview screenshot", str(Path(self.screenshot).parent if self.screenshot
                                                    else self.path.parent),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
        if filename:
            self._load_image(filename)

    def _load_image(self, filename, report=True):
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            message = f"{filename}: {reader.errorString()}"
            if report:
                self._error("Could not open screenshot", message)
            else:
                self.statusBar().showMessage(message)
            return
        self.screenshot = filename
        self.preview.set_image(image)
        self.settings.setValue("preview/screenshot", filename)
        self.clear_image_action.setEnabled(True)

    def clear_image(self):
        self.screenshot = ""
        self.preview.set_image(QImage())
        self.settings.remove("preview/screenshot")
        self.clear_image_action.setEnabled(False)

    @staticmethod
    def _source_error(source):
        if source is None:
            return "Choose the extracted folder containing both HUD files."
        try:
            validate_source(source)
        except (OSError, ValueError) as exc:
            return str(exc)
        return ""

    def setup_hud(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Up HUD Files")
        dialog.resize(660, 200)
        form = QFormLayout(dialog)
        game = self._directory("game")
        install_status = QLabel(str(game) if game else
                                "Choose your ETS2 installation in Tools → Directories.")
        install_status.setTextFormat(Qt.TextFormat.PlainText)
        install_status.setWordWrap(True)
        form.addRow("ETS2 installation", install_status)
        link = QLabel(f'<a href="{EXTRACTOR_URL}">Download the official SCS Game Archive Packer</a>')
        link.setOpenExternalLinks(True)
        form.addRow(link)
        folder = editor_directory() / "source_ui"
        if game:
            archive = str(game / "base_share.scs").replace("'", "''")
            archive_arg = f"'{archive}'"
        else:
            archive_arg = "(Join-Path (Read-Host 'ETS2 installation folder') 'base_share.scs')"
        folder_arg = str(folder).replace("'", "''")
        command = QLineEdit(
            f"New-Item -ItemType Directory -Force -Path '{folder_arg}' | Out-Null; "
            f"& (Read-Host 'Full path to scs_packer.exe') extract {archive_arg} -root '{folder_arg}'")
        command.setReadOnly(True)
        command.setAccessibleName("PowerShell extraction command")
        row = QHBoxLayout()
        row.addWidget(command, 1)
        self._button(row, "Copy command", lambda: QApplication.clipboard().setText(command.text()))
        form.addRow("PowerShell", row)
        instructions = QLabel("Run the command in PowerShell and enter the requested paths. After "
                              "extraction, choose the folder containing both HUD files.")
        instructions.setWordWrap(True)
        form.addRow(instructions)
        entry = QLineEdit(self.directories["source"] or str(folder))
        row = QHBoxLayout()
        row.addWidget(entry, 1)
        self._button(row, "Browse…", partial(self._browse_directory, dialog, entry, "HUD source"))
        form.addRow("HUD source", row)
        feedback = QLabel()
        feedback.setTextFormat(Qt.TextFormat.PlainText)
        feedback.setWordWrap(True)
        form.addRow(feedback)

        def accept_source():
            value = entry.text().strip()
            feedback.setText(self._source_error(Path(expanduser(value)) if value else None))
            if not feedback.text():
                self._set_directories({"source": value})
                dialog.accept()

        buttons = QDialogButtonBox(OK_CANCEL, parent=dialog)
        buttons.accepted.connect(accept_source)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        dialog.exec()

    def change_directories(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Directories")
        dialog.resize(690, 210)
        form = QFormLayout(dialog)
        hints = {
            "game": "Folder containing the ETS2 game archives",
            "source": "Folder containing ui/hud_left.sii and ui/hud_right.sii",
            "output": "Folder where the editor saves the built mod",
            "mod": "Folder where ETS2 loads local mods",
        }
        entries = {}
        for key, label in DIRECTORIES.items():
            entry = entries[key] = QLineEdit(self.directories[key])
            entry.setPlaceholderText(hints[key])
            entry.setAccessibleName(label)
            browse = QPushButton("Browse…")
            browse.setAccessibleName(f"Browse for {label}")
            browse.clicked.connect(partial(self._browse_directory, dialog, entry, label))
            row = QHBoxLayout()
            row.addWidget(entry, 1)
            row.addWidget(browse)
            form.addRow(label, row)
        dialog_buttons(dialog, form)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_directories({key: entry.text().strip() for key, entry in entries.items()})

    def _set_directories(self, directories):
        self.directories.update(directories)
        for key, value in directories.items():
            self.settings.setValue(f"paths/{key}", value)
        self.source_error = self._source_error(self._directory("source"))
        self.build_status.clear()
        self._refresh_operation_controls()

    def _browse_directory(self, dialog, entry, label):
        directory = QFileDialog.getExistingDirectory(dialog, f"Select {label}",
                                                      entry.text() or str(editor_directory()))
        if directory:
            entry.setText(directory)

    def _directory(self, key):
        value = self.directories[key]
        return Path(expanduser(value)) if value else None

    def _build_inputs(self):
        return self.model, self._directory("source"), self._directory("output"), self._directory("game")

    def _refresh_operation_controls(self):
        if self.build_inputs is not None and self.build_inputs != self._build_inputs():
            self.build_inputs = None
            self.build_status.setText("Layout or build settings changed. Build again before installing.")
        idle = self.operation is None
        can_build = not self.source_error and self._directory("output") is not None
        built = self.build_inputs is not None and self.artifact is not None and self.artifact.is_file()
        mod = self._directory("mod")
        for control in (self.setup_button, self.setup_action):
            control.setEnabled(idle)
        for control in (self.build_button, self.build_action):
            control.setEnabled(idle and can_build)
        for control in (self.install_button, self.install_action):
            control.setEnabled(idle and built and mod is not None)
        output = self._directory("output")
        self.output_action.setEnabled(output is not None and output.is_dir())
        if idle and not self.build_status.text():
            if self.source_error:
                message = "Set up HUD files to build a mod."
            elif output is None:
                message = "Choose a build output folder in Tools → Directories."
            elif built and mod is None:
                message = "Choose an ETS2 mod folder in Tools → Directories to install the build."
            else:
                message = "HUD files ready. Build the layout shown in the preview."
            self.build_status.setText(message)
        self.setup_button.setToolTip(self.source_error)
        self.progress.setVisible(not idle)

    def _start_work(self, work, installing=False):
        operation = Operation(work, self)
        operation.setProperty("installing", installing)
        self.operation = operation
        operation.progress.connect(self.statusBar().showMessage)
        operation.success.connect(self._work_succeeded)
        operation.failed.connect(self._work_failed)
        operation.finished.connect(self._work_finished)
        self._refresh_operation_controls()
        self.statusBar().showMessage("Starting installation…" if installing else "Starting build…")
        operation.start()

    @Slot(object)
    def _work_succeeded(self, path):
        if self.operation.property("installing"):
            message = f"Installed {path}. Activate ETS2 Configurable Mirrors in ETS2 Mod Manager."
        else:
            self.artifact = path
            if self.build_inputs is None:
                message = "Build finished for an earlier layout. Build again before installing."
            elif self._directory("mod") is None:
                message = f"Built {path}. Set the ETS2 mod folder in Tools → Directories to install."
            else:
                message = f"Built {path}. Select Install Mod to copy it to ETS2."
        self.build_status.setText(message)
        self.build_status.show()
        self.statusBar().showMessage("Install complete" if self.operation.property("installing")
                                     else "Build complete")

    @Slot(str)
    def _work_failed(self, message):
        action = "Install" if self.operation.property("installing") else "Build"
        if action == "Build":
            self.build_inputs = None
            self.source_error = self._source_error(self._directory("source"))
        self.build_status.setText(f"{action} failed. {message}")
        self.build_status.show()
        self._error(f"{action} failed", message)

    @Slot()
    def _work_finished(self):
        self.operation.deleteLater()
        self.operation = None
        self._refresh_operation_controls()

    def build_mod(self):
        if self.operation:
            return
        self.build_inputs = None
        source, output, mod = (self._directory(key) for key in ("source", "output", "mod"))
        self.source_error = self._source_error(source)
        self.build_status.clear()
        self._refresh_operation_controls()
        if self.source_error or not output:
            self._error("Cannot build mod", self.source_error or "Choose a build output folder.")
            return
        if mod and output.resolve() == mod.resolve():
            self.build_status.setText("Choose an output folder separate from the ETS2 mod folder.")
            self._error("Choose a separate output directory",
                        "Build to a separate folder, then use Install Mod to update the mod directory.")
            return
        work = partial(build, self.model, source, output, game=self._directory("game"))
        self.build_inputs = self._build_inputs()
        self._start_work(work)

    def install_mod(self):
        if self.operation:
            return
        self._refresh_operation_controls()
        if not self.install_button.isEnabled():
            return
        mod = self._directory("mod")
        target = mod / MOD_NAME
        overwrite = target.exists() and target.resolve() != self.artifact.resolve()
        if overwrite and QMessageBox.question(
                self, "Replace installed mod?", f"{target} already exists. Replace it?",
                BUTTON.Yes | BUTTON.No, BUTTON.No) != BUTTON.Yes:
            return
        work = partial(install, self.artifact, mod, overwrite=overwrite, game=self._directory("game"))
        self._start_work(work, installing=True)

    def open_output(self):
        output = self._directory("output")
        if output is not None and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.absolute()))):
            self._error("Could not open output folder", str(output))

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME}</h3><p>Version {VERSION} · {AUTHOR}</p>"
                          "<p>GPL-3.0. Built with Python and Qt for Python.</p>"
                          "<p>Euro Truck Simulator 2 is developed by SCS Software.</p>"
                          f'<p><a href="{PROJECT_URL}">Source, releases, and support</a></p>')

    def show_help(self):
        QMessageBox.information(
            self, APP_NAME,
            "Select a mirror to drag it or resize it with the eight handles. Use Arrow keys "
            "for one-unit nudges and Shift+Arrow for ten-unit nudges. Turn on Edit padding in "
            "preview to drag the amber frame handles or set Frame padding numerically.\n\n"
            "Build Mod uses the layout shown in the editor. Select extracted HUD files "
            "from your target ETS2 version in Set Up HUD Files. After installing the build, "
            "activate it in ETS2 Mod Manager. The project link in About has more help.")

    def _error(self, title, message):
        self.statusBar().showMessage(title)
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event):
        if self.operation:
            self.statusBar().showMessage("Wait for the build or installation to finish before closing.")
            event.ignore()
        elif self._discard_allowed():
            super().closeEvent(event)
        else:
            event.ignore()
