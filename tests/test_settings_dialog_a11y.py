"""Accessibility contracts for the wx Settings dialog."""

from __future__ import annotations

import importlib
import sys
import types

from portkeydrop.settings import Settings


# -- Fake wx stubs for headless testing --------------------------------
#
# These track HWND creation order so we can verify that labels are
# always created before their controls (the key invariant for NVDA).

_creation_order: list[object] = []


class _Window:
    def __init__(self, parent=None, **_kw):
        self.parent = parent
        self.children: list[_Window] = []
        self._name = ""
        self._tooltip = ""
        self.focused = False
        _creation_order.append(self)
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def SetName(self, name: str) -> None:
        self._name = name

    def GetName(self) -> str:
        return self._name

    def SetFocus(self) -> None:
        self.focused = True

    def SetToolTip(self, text: str) -> None:
        self._tooltip = text

    def GetChildren(self):
        return list(self.children)

    def Bind(self, *_a, **_kw):
        return None

    def SetSizer(self, sizer):
        self.sizer = sizer


class _Dialog(_Window):
    def CreateStdDialogButtonSizer(self, _flags):
        return _BoxSizer()


class _Panel(_Window):
    pass


class _Notebook(_Window):
    def __init__(self, parent=None, **_kw):
        super().__init__(parent)
        self.pages: list[tuple[_Panel, str]] = []

    def AddPage(self, panel, title: str):
        self.pages.append((panel, title))


class _BoxSizer:
    def __init__(self, *_a, **_kw):
        self.items: list = []

    def Add(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def AddStretchSpacer(self, *_a, **_kw):
        return None


class _Control(_Window):
    def __init__(self, parent=None, **_kw):
        super().__init__(parent)
        self._value = None
        self._selection = 0

    def SetValue(self, value):
        self._value = value

    def GetValue(self):
        return self._value


class _TextCtrl(_Control):
    def GetClassName(self) -> str:
        return "wxTextCtrl"


class _SpinCtrl(_Control):
    def __init__(self, parent=None, **_kw):
        super().__init__(parent)
        self._editor = _TextCtrl(self)


class _Choice(_Control):
    def __init__(self, parent=None, choices=None, **_kw):
        super().__init__(parent)
        self._choices = choices or []

    def SetSelection(self, idx: int):
        self._selection = idx

    def GetStringSelection(self) -> str:
        return self._choices[self._selection]


class _CheckBox(_Control):
    pass


class _StaticText(_Window):
    created: list[_StaticText] = []

    def __init__(self, parent=None, label: str = "", **_kw):
        super().__init__(parent)
        self.label = label
        self._label_for = None
        _StaticText.created.append(self)

    def SetMinSize(self, *_a, **_kw):
        return None

    def Wrap(self, *_a, **_kw):
        return None

    def SetLabelFor(self, ctrl):
        self._label_for = ctrl


# -- Helpers -----------------------------------------------------------


def _make_fake_wx():
    return types.SimpleNamespace(
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
        CallAfter=lambda fn, *a, **kw: fn(*a, **kw),
    )


def _load_dialog(monkeypatch):
    """Import SettingsDialog with fake wx and return a fresh instance."""
    monkeypatch.setitem(sys.modules, "wx", _make_fake_wx())
    _StaticText.created = []
    _creation_order.clear()
    mod = importlib.import_module("portkeydrop.dialogs.settings")
    mod = importlib.reload(mod)
    return mod.SettingsDialog(None, Settings())


# -- Tests -------------------------------------------------------------


def test_all_controls_have_unambiguous_accessible_names(monkeypatch):
    """Every control must carry a descriptive accessible name."""
    dlg = _load_dialog(monkeypatch)

    expected = {
        # Transfer
        "concurrent_spin": "Concurrent transfers count",
        "overwrite_choice": "Overwrite mode",
        "resume_check": "Resume partial transfers",
        "preserve_ts_check": "Preserve timestamps",
        "follow_symlinks_check": "Follow symlinks",
        "download_dir_text": "Download directory",
        # Display
        "announce_count_check": "Announce file count",
        "progress_interval_spin": "Progress interval",
        "show_hidden_check": "Show hidden files",
        "sort_by_choice": "Sort by",
        "sort_asc_check": "Sort ascending",
        "date_format_choice": "Date format",
        # Connection
        "default_proto_choice": "Default protocol",
        "timeout_spin": "Connection timeout",
        "keepalive_spin": "Keepalive interval",
        "retries_spin": "Maximum retries",
        "passive_check": "Passive mode",
        "verify_keys_choice": "Verify host keys",
        "remember_local_folder_check": "Remember last local folder on startup",
        # Speech
        "speech_rate_spin": "Speech rate",
        "speech_volume_spin": "Speech volume",
        "verbosity_choice": "Speech verbosity",
    }

    for attr, name in expected.items():
        control = getattr(dlg, attr)
        assert control.GetName() == name, f"{attr}: expected {name!r}, got {control.GetName()!r}"


def test_labeled_controls_have_label_for_links(monkeypatch):
    """Non-checkbox controls must be linked to their label via SetLabelFor."""
    dlg = _load_dialog(monkeypatch)

    linked = {lbl._label_for for lbl in _StaticText.created if lbl._label_for is not None}

    controls_needing_labels = [
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
    ]

    for attr in controls_needing_labels:
        ctrl = getattr(dlg, attr)
        assert ctrl in linked, f"{attr} is not linked to any label via SetLabelFor"


def test_label_hwnd_created_before_control(monkeypatch):
    """Every label must be created before its control in HWND order.

    NVDA resolves labels by walking backward through sibling HWNDs.
    If a control's HWND is created before its label, NVDA picks up the
    wrong label or none at all.
    """
    _load_dialog(monkeypatch)

    for lbl in _StaticText.created:
        if lbl._label_for is None:
            continue
        ctrl = lbl._label_for
        lbl_idx = _creation_order.index(lbl)
        ctrl_idx = _creation_order.index(ctrl)
        assert lbl_idx < ctrl_idx, (
            f"label {lbl.label!r} (idx {lbl_idx}) created AFTER "
            f"control {ctrl.GetName()!r} (idx {ctrl_idx})"
        )


def test_spin_inner_editors_carry_field_context(monkeypatch):
    """The inner wxTextCtrl of each SpinCtrl must be named with field context."""
    dlg = _load_dialog(monkeypatch)

    spins = [
        dlg.concurrent_spin,
        dlg.progress_interval_spin,
        dlg.timeout_spin,
        dlg.keepalive_spin,
        dlg.retries_spin,
        dlg.speech_rate_spin,
        dlg.speech_volume_spin,
    ]

    for spin in spins:
        editor = spin.GetChildren()[0]
        expected = f"{spin.GetName()} value"
        assert editor.GetName() == expected, (
            f"inner editor of {spin.GetName()!r}: expected {expected!r}, got {editor.GetName()!r}"
        )


def test_spin_controls_have_tooltips(monkeypatch):
    """Spin controls and their inner editors must have tooltips as MSAA fallback."""
    dlg = _load_dialog(monkeypatch)

    spins = [
        dlg.concurrent_spin,
        dlg.progress_interval_spin,
        dlg.timeout_spin,
        dlg.keepalive_spin,
        dlg.retries_spin,
        dlg.speech_rate_spin,
        dlg.speech_volume_spin,
    ]

    for spin in spins:
        name = spin.GetName()
        assert spin._tooltip == name, f"{name}: spin missing tooltip"
        editor = spin.GetChildren()[0]
        assert editor._tooltip == name, f"{name}: inner editor missing tooltip"


def test_notebook_receives_initial_focus(monkeypatch):
    """Tab control must receive focus on dialog open for keyboard navigation."""
    dlg = _load_dialog(monkeypatch)
    assert dlg.notebook.focused is True
