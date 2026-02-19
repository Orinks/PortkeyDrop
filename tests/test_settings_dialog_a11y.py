"""Accessibility contracts for the Settings dialog."""

from __future__ import annotations

import importlib
import sys
import types

from portkeydrop.settings import Settings


class _FakeEvent:
    def __init__(self, shown: bool = False):
        self._shown = shown
        self.skipped = False

    def IsShown(self) -> bool:
        return self._shown

    def Skip(self) -> None:
        self.skipped = True


class _Window:
    def __init__(self, parent=None):
        self.parent = parent
        self.children = []
        self._name = ""
        self.focused = False
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def SetName(self, name: str) -> None:
        self._name = name

    def GetName(self) -> str:
        return self._name

    def SetFocus(self) -> None:
        self.focused = True

    def GetChildren(self):
        return list(self.children)

    def Bind(self, *_args, **_kwargs):
        return None

    def SetSizer(self, sizer):
        self.sizer = sizer


class _Dialog(_Window):
    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)

    def CreateStdDialogButtonSizer(self, _flags):
        return _BoxSizer()


class _Panel(_Window):
    pass


class _Notebook(_Window):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages = []

    def AddPage(self, panel, title: str):
        self.pages.append((panel, title))


class _BoxSizer:
    def __init__(self, *_args, **_kwargs):
        self.items = []

    def Add(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def AddStretchSpacer(self, *_args, **_kwargs):
        return None


class _Control(_Window):
    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)
        self._value = None
        self._selection = 0
        self._tooltip = ""

    def SetValue(self, value):
        self._value = value

    def GetValue(self):
        return self._value

    def SetToolTip(self, text: str):
        self._tooltip = text


class _TextCtrl(_Control):
    def GetClassName(self) -> str:
        return "wxTextCtrl"


class _SpinCtrl(_Control):
    def __init__(self, parent=None, **_kwargs):
        super().__init__(parent)
        self._editor = _TextCtrl(self)


class _Choice(_Control):
    def __init__(self, parent=None, choices=None):
        super().__init__(parent)
        self._choices = choices or []

    def SetSelection(self, idx: int):
        self._selection = idx

    def GetStringSelection(self) -> str:
        return self._choices[self._selection]


class _CheckBox(_Control):
    pass


class _StaticText(_Window):
    created = []

    def __init__(self, parent=None, label: str = ""):
        super().__init__(parent)
        self.label = label
        self._label_for = None
        _StaticText.created.append(self)

    def SetMinSize(self, *_args, **_kwargs):
        return None

    def Wrap(self, *_args, **_kwargs):
        return None

    def SetLabelFor(self, ctrl):
        self._label_for = ctrl


class _WxModule(types.SimpleNamespace):
    pass


def _load_settings_dialog_module(monkeypatch):
    fake_wx = _WxModule(
        Dialog=_Dialog,
        Window=_Window,
        Panel=_Panel,
        Notebook=_Notebook,
        BoxSizer=_BoxSizer,
        StaticText=_StaticText,
        SpinCtrl=_SpinCtrl,
        Choice=_Choice,
        CheckBox=_CheckBox,
        TextCtrl=_TextCtrl,
        Control=_Control,
        ShowEvent=_FakeEvent,
        WindowCreateEvent=_FakeEvent,
        EVT_SHOW=object(),
        EVT_WINDOW_CREATE=object(),
        DEFAULT_DIALOG_STYLE=1,
        RESIZE_BORDER=2,
        VERTICAL=1,
        HORIZONTAL=2,
        EXPAND=4,
        ALL=8,
        LEFT=16,
        RIGHT=32,
        TOP=64,
        ALIGN_CENTER_VERTICAL=128,
        OK=1,
        CANCEL=2,
        CallAfter=lambda fn, *a, **k: fn(*a, **k),
    )
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    _StaticText.created = []
    module = importlib.import_module("portkeydrop.dialogs.settings")
    module = importlib.reload(module)
    return module


def test_settings_dialog_assigns_unambiguous_names_and_label_links(monkeypatch):
    module = _load_settings_dialog_module(monkeypatch)
    dlg = module.SettingsDialog(None, Settings())

    expected_names = {
        "concurrent_spin": "Concurrent transfers",
        "overwrite_choice": "Overwrite mode",
        "resume_check": "Resume partial transfers",
        "preserve_ts_check": "Preserve timestamps",
        "follow_symlinks_check": "Follow symlinks",
        "download_dir_text": "Download directory",
        "announce_count_check": "Announce file count",
        "progress_interval_spin": "Progress interval",
        "show_hidden_check": "Show hidden files",
        "sort_by_choice": "Sort by",
        "sort_asc_check": "Sort ascending",
        "date_format_choice": "Date format",
        "default_proto_choice": "Default protocol",
        "timeout_spin": "Connection timeout",
        "keepalive_spin": "Keepalive interval",
        "retries_spin": "Maximum retries",
        "passive_check": "Passive mode",
        "verify_keys_choice": "Verify host keys",
        "remember_local_folder_check": "Remember last local folder on startup",
        "speech_rate_spin": "Speech rate",
        "speech_volume_spin": "Speech volume",
        "verbosity_choice": "Speech verbosity",
    }

    for attr, expected in expected_names.items():
        control = getattr(dlg, attr)
        assert control.GetName() == expected

    linked_controls = {lbl._label_for for lbl in _StaticText.created if lbl._label_for is not None}
    for attr in [
        "concurrent_spin",
        "overwrite_choice",
        "download_dir_text",
        "progress_interval_spin",
        "sort_by_choice",
        "date_format_choice",
        "default_proto_choice",
        "timeout_spin",
        "keepalive_spin",
        "retries_spin",
        "verify_keys_choice",
        "speech_rate_spin",
        "speech_volume_spin",
        "verbosity_choice",
    ]:
        assert getattr(dlg, attr) in linked_controls


def test_spin_controls_name_inner_editor_with_field_context(monkeypatch):
    module = _load_settings_dialog_module(monkeypatch)
    dlg = module.SettingsDialog(None, Settings())

    spin_controls = [
        dlg.concurrent_spin,
        dlg.progress_interval_spin,
        dlg.timeout_spin,
        dlg.keepalive_spin,
        dlg.retries_spin,
        dlg.speech_rate_spin,
        dlg.speech_volume_spin,
    ]

    for spin in spin_controls:
        editor = spin.GetChildren()[0]
        assert editor.GetName() == f"{spin.GetName()} value"


def test_settings_dialog_focuses_tab_control_on_open(monkeypatch):
    module = _load_settings_dialog_module(monkeypatch)
    dlg = module.SettingsDialog(None, Settings())

    assert dlg.notebook.focused is True
