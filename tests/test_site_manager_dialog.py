"""Tests for SiteManagerDialog, including show/hide password toggle."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock
import pytest


# ---------------------------------------------------------------------------
# Minimal wx stub for SiteManagerDialog
# ---------------------------------------------------------------------------


class _Window:
    def __init__(self, parent=None, **_kw):
        pass

    def Bind(self, *a, **kw):
        pass

    def SetName(self, *a):
        pass

    def SetSizer(self, *a):
        pass

    def Layout(self):
        pass

    def SetFocus(self):
        pass

    def Destroy(self):
        pass

    def GetContainingSizer(self):
        return _Sizer()

    def GetWindowStyle(self):
        return 0

    def GetValue(self):
        return ""

    def SetValue(self, v):
        self._value = v

    def SetLabel(self, v):
        pass


class _Dialog(_Window):
    def __init__(self, parent=None, title="", size=None, style=0, **_kw):
        pass

    def EndModal(self, r):
        pass


class _Sizer:
    def __init__(self):
        self._index = 0

    def GetItem(self, ctrl):
        return self

    def GetProportion(self):
        return 1

    def GetFlag(self):
        return 0

    def GetBorder(self):
        return 0

    def GetItemIndex(self, ctrl):
        return self._index

    def Detach(self, ctrl):
        pass

    def Insert(self, index, ctrl, proportion, flags, border):
        self._index = index

    def Replace(self, old, new):
        pass

    def Add(self, *a, **kw):
        pass


class _TextCtrl(_Window):
    def __init__(self, parent=None, style=0, **_kw):
        self._parent = parent
        self._style = style
        self._value = ""
        self._sizer = _Sizer()
        self._moved_before = None
        self._insert_end_called = False

    def GetParent(self):
        return self._parent

    def GetWindowStyle(self):
        return self._style

    def GetValue(self):
        return self._value

    def SetValue(self, v):
        self._value = v

    def GetContainingSizer(self):
        return self._sizer

    def MoveBeforeInTabOrder(self, other):
        self._moved_before = other

    def SetInsertionPointEnd(self):
        self._insert_end_called = True

    def Destroy(self):
        pass


class _Button(_Window):
    def __init__(self, parent=None, id=None, label="", **_kw):
        self._id = id
        self._label = label
        self._name = ""

    def SetLabel(self, v):
        self._label = v

    def SetName(self, v):
        self._name = v

    def SetDefault(self):
        pass

    def GetId(self):
        return self._id


class _Choice(_Window):
    def __init__(self, *a, choices=None, **kw):
        self._choices = choices or []

    def SetSelection(self, i):
        pass

    def GetStringSelection(self):
        return self._choices[0] if self._choices else ""


class _CheckBox(_Window):
    def __init__(self, *a, **kw):
        self._value = False
        self._enabled = True
        self._name = ""

    def SetName(self, value):
        self._name = value

    def Enable(self, enabled):
        self._enabled = enabled

    def SetValue(self, value):
        self._value = value

    def GetValue(self):
        return self._value


class _StaticText(_Window):
    pass


class _FlexGridSizer(_Sizer):
    def __init__(self, *a, **kw):
        pass

    def AddGrowableCol(self, *a):
        pass

    def Add(self, *a, **kw):
        pass


class _BoxSizer(_Sizer):
    def __init__(self, *a, **kw):
        pass

    def Add(self, *a, **kw):
        pass


class _ListBox(_Window):
    def __init__(self, *a, **kw):
        self._items = []
        self._selection = -1
        self._focused = False

    def Clear(self):
        self._items = []
        self._selection = -1

    def Append(self, label, data=None):
        self._items.append((label, data))

    def GetSelection(self):
        return self._selection

    def SetSelection(self, i):
        self._selection = i

    def GetCount(self):
        return len(self._items)

    def GetClientData(self, i):
        if 0 <= i < len(self._items):
            return self._items[i][1]
        return None

    def SetFocus(self):
        self._focused = True

    def Bind(self, *a, **kw):
        pass


def _make_fake_wx():
    wx = types.ModuleType("wx")
    wx.Dialog = _Dialog
    wx.Frame = _Window
    wx.Panel = _Window
    wx.TextCtrl = _TextCtrl
    wx.Button = _Button
    wx.CheckBox = _CheckBox
    wx.Choice = _Choice
    wx.StaticText = _StaticText
    wx.FlexGridSizer = _FlexGridSizer
    wx.BoxSizer = _BoxSizer
    wx.ListBox = _ListBox
    wx.StaticBox = _Window
    wx.StaticBoxSizer = _BoxSizer
    wx.FileDialog = _Dialog
    wx.OK = 5100
    wx.ID_OK = 5100
    wx.CANCEL = 5101
    wx.ICON_ERROR = 0x10000
    wx.ICON_INFORMATION = 0x20000
    wx.ALIGN_CENTER_VERTICAL = 1
    wx.ALIGN_RIGHT = 2
    wx.LEFT = 4
    wx.RIGHT = 8
    wx.TOP = 16
    wx.BOTTOM = 32
    wx.EXPAND = 64
    wx.ALL = 128
    wx.VERTICAL = 256
    wx.HORIZONTAL = 512
    wx.TE_PASSWORD = 64
    wx.DEFAULT_DIALOG_STYLE = 128
    wx.RESIZE_BORDER = 256
    wx.FD_OPEN = 512
    wx.FD_FILE_MUST_EXIST = 1024
    wx.NOT_FOUND = -1
    wx.ID_CANCEL = 5101
    wx.WXK_ESCAPE = 27
    wx.EVT_BUTTON = object()
    wx.EVT_CHOICE = object()
    wx.EVT_LISTBOX = object()
    wx.EVT_LISTBOX_DCLICK = object()
    wx.EVT_CHAR_HOOK = object()
    wx.WXK_RETURN = 13
    wx.MessageBox = MagicMock(return_value=wx.OK)
    wx.CallAfter = lambda fn, *a, **kw: fn(*a, **kw)
    return wx


@pytest.fixture
def dialog_module(monkeypatch):
    fake_wx = _make_fake_wx()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    sys.modules.pop("portkeydrop.dialogs.site_manager", None)
    mod = importlib.import_module("portkeydrop.dialogs.site_manager")
    return mod, fake_wx


def _make_dialog(mod, fake_wx, masked=True):
    site_manager = MagicMock()
    site_manager.sites = []
    dlg = object.__new__(mod.SiteManagerDialog)
    dlg._site_manager = site_manager
    dlg._selected_site = None
    dlg._connect_requested = False

    # Password ctrl
    pw = _TextCtrl(style=fake_wx.TE_PASSWORD if masked else 0)
    pw.SetValue("secret123")
    dlg.password_text = pw

    dlg.show_password_btn = _Button()
    dlg.Layout = MagicMock()
    return dlg


class TestTogglePassword:
    def test_show_reveals_password(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        # New ctrl is plain text (no TE_PASSWORD)
        assert dlg.password_text.GetWindowStyle() == 0
        # Value preserved
        assert dlg.password_text.GetValue() == "secret123"
        # Button updated
        assert dlg.show_password_btn._label == "H&ide"
        assert dlg.show_password_btn._name == "Hide password"
        dlg.Layout.assert_called_once()

    def test_hide_masks_password(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=False)
        dlg.password_text.SetValue("secret123")

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        assert dlg.password_text.GetWindowStyle() == fake_wx.TE_PASSWORD
        assert dlg.show_password_btn._label == "S&how"
        assert dlg.show_password_btn._name == "Show password"

    def test_value_preserved_on_toggle(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)
        dlg.password_text.SetValue("mypassword")

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        assert dlg.password_text.GetValue() == "mypassword"

    def test_toggle_handles_negative_sizer_index(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)
        dlg.password_text.GetContainingSizer()._index = -1

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        assert dlg.password_text.GetWindowStyle() == 0

    def test_toggle_ignores_tab_order_errors(self, dialog_module, monkeypatch):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)

        def _boom(self, _other):
            raise RuntimeError("tab order unsupported")

        monkeypatch.setattr(_TextCtrl, "MoveBeforeInTabOrder", _boom)

        # Should not raise even if tab order call fails.
        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())
        assert dlg.password_text.GetValue() == "secret123"


class TestSiteManagerDialogInit:
    def test_init_creates_show_password_btn(self, dialog_module):
        """__init__ should wire up the Show password button."""
        from portkeydrop.sites import SiteManager

        mod, fake_wx = dialog_module
        site_manager = MagicMock(spec=SiteManager)
        site_manager.sites = []

        dlg = mod.SiteManagerDialog(None, site_manager)

        assert hasattr(dlg, "show_password_btn")
        assert dlg.show_password_btn._label == "S&how"
        assert dlg.show_password_btn._name == "Show password"
        assert hasattr(dlg, "password_text")

    def test_init_creates_close_button_with_cancel_id(self, dialog_module):
        from portkeydrop.sites import SiteManager

        mod, fake_wx = dialog_module
        site_manager = MagicMock(spec=SiteManager)
        site_manager.sites = []

        dlg = mod.SiteManagerDialog(None, site_manager)

        assert hasattr(dlg, "close_btn")
        assert dlg.close_btn._label == "&Close"
        assert dlg.close_btn.GetId() == fake_wx.ID_CANCEL


class TestEscapeKeyHandler:
    """Issue #34: SiteManagerDialog should close on Escape."""

    def test_escape_calls_end_modal_cancel(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx)
        dlg.EndModal = MagicMock()

        event = MagicMock()
        event.GetKeyCode.return_value = fake_wx.WXK_ESCAPE

        mod.SiteManagerDialog._on_char_hook(dlg, event)

        dlg.EndModal.assert_called_once_with(fake_wx.ID_CANCEL)

    def test_non_escape_key_skips(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx)
        dlg.EndModal = MagicMock()

        event = MagicMock()
        event.GetKeyCode.return_value = 65  # 'A'

        mod.SiteManagerDialog._on_char_hook(dlg, event)

        dlg.EndModal.assert_not_called()
        event.Skip.assert_called_once()


class TestRemoveFocusManagement:
    """Issue #39: Focus should move to next item after removing a site."""

    def _make_dialog_with_sites(self, mod, fake_wx, site_names):
        from portkeydrop.sites import Site

        sites = [Site(name=n) for n in site_names]
        site_manager = MagicMock()
        site_manager.sites = list(sites)

        def remove_site(site_id):
            site_manager.sites = [s for s in site_manager.sites if s.id != site_id]

        site_manager.remove = remove_site

        dlg = object.__new__(mod.SiteManagerDialog)
        dlg._site_manager = site_manager
        dlg._selected_site = None
        dlg._connect_requested = False
        dlg.site_list = _ListBox()
        dlg.name_text = _TextCtrl()
        dlg.protocol_choice = _Choice(choices=["sftp", "ftp", "ftps"])
        dlg.host_text = _TextCtrl()
        dlg.port_text = _TextCtrl()
        dlg.username_text = _TextCtrl()
        dlg.password_text = _TextCtrl()
        dlg.key_path_text = _TextCtrl()
        dlg.initial_dir_text = _TextCtrl()
        dlg.show_password_btn = _Button()
        dlg.Layout = MagicMock()

        # Populate the list
        for s in sites:
            dlg.site_list.Append(s.name, s.id)

        return dlg, sites

    def test_remove_middle_item_focuses_next(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["A", "B", "C"])

        # Select "B" (index 1)
        dlg.site_list.SetSelection(1)
        dlg._selected_site = sites[1]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # Should focus on item at index 1 (now "C")
        assert dlg.site_list._selection == 1
        assert dlg.site_list._focused is True

    def test_remove_last_item_focuses_previous(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["A", "B", "C"])

        # Select "C" (index 2)
        dlg.site_list.SetSelection(2)
        dlg._selected_site = sites[2]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # Should focus on last remaining item (index 1, "B")
        assert dlg.site_list._selection == 1
        assert dlg.site_list._focused is True

    def test_remove_only_item_focuses_list(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["A"])

        dlg.site_list.SetSelection(0)
        dlg._selected_site = sites[0]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # No items left, focus should go to the list itself
        assert dlg.site_list.GetCount() == 0
        assert dlg.site_list._focused is True

    def test_remove_with_stale_selection_uses_selected_site_index(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["A", "B", "C"])

        # Simulate stale list selection while a site is still logically selected.
        dlg.site_list.SetSelection(fake_wx.NOT_FOUND)
        dlg._selected_site = sites[1]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # Should still select/focus index 1 (now "C").
        assert dlg.site_list._selection == 1
        assert dlg.site_list._focused is True

    def test_remove_updates_selected_site_to_remaining_selection(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["A", "B", "C"])

        dlg.site_list.SetSelection(1)
        dlg._selected_site = sites[1]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # Logical selection should track the newly selected row ("C").
        assert dlg._selected_site is dlg._site_manager.sites[1]

    def test_remove_populates_form_with_next_site(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, sites = self._make_dialog_with_sites(mod, fake_wx, ["Alpha", "Beta", "Gamma"])
        sites[2].host = "gamma.example.com"

        # Select "Beta" (index 1)
        dlg.site_list.SetSelection(1)
        dlg._selected_site = sites[1]

        mod.SiteManagerDialog._on_remove(dlg, MagicMock())

        # Form should reflect "Gamma" (now at index 1), not the removed "Beta".
        assert dlg.host_text._value == "gamma.example.com"


class TestPortValidation:
    """Port field validation in _update_site_from_form."""

    def _make_form_dialog(self, mod, fake_wx):
        from portkeydrop.sites import Site

        site = Site(name="Test")
        site_manager = MagicMock()

        dlg = object.__new__(mod.SiteManagerDialog)
        dlg._site_manager = site_manager
        dlg._selected_site = site
        dlg.name_text = _TextCtrl()
        dlg.name_text.SetValue("Test")
        dlg.protocol_choice = _Choice(choices=["sftp", "ftp", "ftps"])
        dlg.host_text = _TextCtrl()
        dlg.port_text = _TextCtrl()
        dlg.username_text = _TextCtrl()
        dlg.password_text = _TextCtrl()
        dlg.key_path_text = _TextCtrl()
        dlg.initial_dir_text = _TextCtrl()
        dlg.initial_dir_text.SetValue("/home")
        return dlg, site

    def test_valid_port_accepted(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, site = self._make_form_dialog(mod, fake_wx)
        dlg.port_text.SetValue("2222")

        result = mod.SiteManagerDialog._update_site_from_form(dlg, site)

        assert result is True
        assert site.port == 2222

    def test_empty_port_defaults_to_zero(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, site = self._make_form_dialog(mod, fake_wx)
        dlg.port_text.SetValue("")

        result = mod.SiteManagerDialog._update_site_from_form(dlg, site)

        assert result is True
        assert site.port == 0

    def test_non_numeric_port_shows_error_and_returns_false(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg, site = self._make_form_dialog(mod, fake_wx)
        dlg.port_text.SetValue("abc")
        dlg.port_text.SetFocus = MagicMock()

        result = mod.SiteManagerDialog._update_site_from_form(dlg, site)

        assert result is False
        fake_wx.MessageBox.assert_called()
        dlg.port_text.SetFocus.assert_called_once()
