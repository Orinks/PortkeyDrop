"""Tests for MigrationDialog selection behavior."""

from __future__ import annotations

import importlib

import pytest

from tests._wx_stub import load_module_with_fake_wx


class _FakeCheckBox:
    def __init__(self, _parent, label: str = "") -> None:
        self.label = label
        self._value = False

    def SetValue(self, value: bool) -> None:
        self._value = value

    def GetValue(self) -> bool:
        return self._value

    def SetFocus(self) -> None:
        pass


class _FakeButtonSizer:
    def AddButton(self, _button) -> None:
        pass

    def Realize(self) -> None:
        pass


class _FakeDialog:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def SetSizerAndFit(self, _sizer) -> None:
        pass

    def Bind(self, *_args, **_kwargs) -> None:
        pass

    def EndModal(self, _result: int) -> None:
        pass


@pytest.fixture
def migration_dialog_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx(
        "portkeydrop.ui.dialogs.migration_dialog",
        monkeypatch,
    )
    fake_wx.Dialog = _FakeDialog
    fake_wx.CheckBox = _FakeCheckBox
    fake_wx.StdDialogButtonSizer = _FakeButtonSizer
    fake_wx.DEFAULT_DIALOG_STYLE = 0
    fake_wx.RIGHT = 0
    fake_wx.BOTTOM = 0
    fake_wx.ALIGN_RIGHT = 0
    fake_wx.ID_CANCEL = 0
    fake_wx.WXK_ESCAPE = 27
    module = importlib.reload(module)
    return module


def test_migration_dialog_checkboxes_default_selected(migration_dialog_module):
    dialog = migration_dialog_module.MigrationDialog(
        None,
        [("Sites & connections", "sites.json"), ("Known SSH hosts", "known_hosts")],
    )

    assert all(checkbox.GetValue() for _, checkbox in dialog._checkboxes)


def test_get_selected_filenames_returns_checked_items_only(migration_dialog_module):
    dialog = migration_dialog_module.MigrationDialog(
        None,
        [("Sites & connections", "sites.json"), ("Known SSH hosts", "known_hosts")],
    )
    dialog._checkboxes[1][1].SetValue(False)

    assert dialog.get_selected_filenames() == ["sites.json"]
