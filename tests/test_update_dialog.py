"""Tests for the update available dialog."""

from __future__ import annotations

import importlib
import sys
import types


class _Window:
    def __init__(self, parent=None, **_kwargs):
        self.parent = parent
        self.children = []
        self.sizer = None
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def SetSizer(self, sizer):
        self.sizer = sizer


class _Dialog(_Window):
    def __init__(self, parent=None, title="", style=0, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.title = title
        self.style = style
        self.size = None
        self.centered = False

    def SetSize(self, size):
        self.size = size

    def CenterOnParent(self):
        self.centered = True


class _StaticText(_Window):
    def __init__(self, parent=None, label="", **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.label = label


class _TextCtrl(_Window):
    def __init__(self, parent=None, value="", style=0, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.value = value
        self.style = style
        self.name = ""
        self.focused = False
        self.insertion_point = None

    def SetName(self, name):
        self.name = name

    def SetFocus(self):
        self.focused = True

    def SetInsertionPoint(self, index):
        self.insertion_point = index


class _Button(_Window):
    def __init__(self, parent=None, id=None, label="", **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.id = id
        self.label = label
        self.is_default = False

    def SetDefault(self):
        self.is_default = True


class _BoxSizer:
    def __init__(self, orient):
        self.orient = orient
        self.items = []

    def Add(self, *args):
        self.items.append(args)


class _StdDialogButtonSizer:
    def __init__(self):
        self.buttons = []
        self.realized = False

    def AddButton(self, btn):
        self.buttons.append(btn)

    def Realize(self):
        self.realized = True


def _fake_wx():
    return types.SimpleNamespace(
        Dialog=_Dialog,
        Window=_Window,
        StaticText=_StaticText,
        TextCtrl=_TextCtrl,
        Button=_Button,
        BoxSizer=_BoxSizer,
        StdDialogButtonSizer=_StdDialogButtonSizer,
        DEFAULT_DIALOG_STYLE=1,
        RESIZE_BORDER=2,
        VERTICAL=1,
        ALL=2,
        EXPAND=4,
        LEFT=8,
        RIGHT=16,
        TE_MULTILINE=32,
        TE_READONLY=64,
        TE_RICH2=128,
        HSCROLL=256,
        ID_OK=100,
        ID_CANCEL=101,
    )


def _load_dialog_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "wx", _fake_wx())
    sys.modules.pop("portkeydrop.ui.dialogs.update_dialog", None)
    return importlib.import_module("portkeydrop.ui.dialogs.update_dialog")


def test_update_dialog_sets_title_and_note_fields(monkeypatch):
    module = _load_dialog_module(monkeypatch)
    parent = object()
    dlg = module.UpdateAvailableDialog(
        parent,
        current_version="1.0.0",
        new_version="1.2.0",
        channel_label="Stable",
        release_notes="  Fixed issues  ",
    )

    assert dlg.title == "Stable Update Available"
    assert dlg.size == (500, 420)
    assert dlg.centered is True
    assert dlg.release_notes_text.value == "Fixed issues"
    assert dlg.release_notes_text.name == "Update release notes"
    assert dlg.release_notes_text.focused is True
    assert dlg.release_notes_text.insertion_point == 0


def test_update_dialog_uses_default_release_notes_when_missing(monkeypatch):
    module = _load_dialog_module(monkeypatch)
    dlg = module.UpdateAvailableDialog(
        None,
        current_version="1.0.0",
        new_version="1.2.0",
        channel_label="Nightly",
        release_notes="",
    )

    assert dlg.title == "Nightly Update Available"
    assert dlg.release_notes_text.value == "No release notes available."
