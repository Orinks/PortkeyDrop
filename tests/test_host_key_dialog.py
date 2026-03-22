"""Tests for HostKeyDialog (headless, wx-stubbed)."""

from __future__ import annotations

import importlib
import sys
import types


# ---------------------------------------------------------------------------
# Minimal wx / wx.lib.sized_controls stubs for headless testing
# ---------------------------------------------------------------------------


class _Window:
    def __init__(self, parent=None, **_kw):
        self.parent = parent
        self.children: list[_Window] = []
        self._bound: list[tuple] = []
        self._focused = False
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def Bind(self, event, handler):
        self._bound.append((event, handler))

    def SetFocus(self) -> None:
        self._focused = True

    def Fit(self) -> None:
        pass

    def SetMinSize(self, _size) -> None:
        pass

    def SetName(self, name: str) -> None:
        self.name = name

    def EndModal(self, result: int) -> None:
        self._modal_result = result


class _SizedDialog(_Window):
    def __init__(self, parent=None, title: str = "", style: int = 0, **_kw):
        super().__init__(parent)
        self.title = title
        self._pane = _SizedPanel(self)

    def GetContentsPane(self) -> "_SizedPanel":
        return self._pane


class _SizedPanel(_Window):
    def SetSizerType(self, _sizer_type: str) -> None:
        pass


class _StaticText(_Window):
    created: list["_StaticText"] = []

    def __init__(self, parent=None, label: str = "", **_kw):
        super().__init__(parent)
        self.label = label
        _StaticText.created.append(self)


class _Button(_Window):
    def __init__(self, parent=None, label: str = "", id: int | None = None, **_kw):
        super().__init__(parent)
        self.label = label
        self.id = id
        self._default = False

    def SetDefault(self) -> None:
        self._default = True


class _TextCtrl(_Window):
    def __init__(self, parent=None, value: str = "", style: int = 0, size=None, **_kw):
        super().__init__(parent)
        self.value = value
        self.style = style
        self.size = size


_EVT_BUTTON = object()
_EVT_CHAR_HOOK = object()


def _make_wx_modules():
    """Build a fake wx module tree that supports `import wx.lib.sized_controls as sc`."""
    # wx.lib.sized_controls
    fake_sc = types.ModuleType("wx.lib.sized_controls")
    fake_sc.SizedDialog = _SizedDialog
    fake_sc.SizedPanel = _SizedPanel

    # wx.lib
    fake_lib = types.ModuleType("wx.lib")
    fake_lib.sized_controls = fake_sc

    # wx (top-level) — must be a ModuleType so `wx.lib` attribute access works
    fake_wx = types.ModuleType("wx")
    fake_wx.DEFAULT_DIALOG_STYLE = 1
    fake_wx.RESIZE_BORDER = 2
    fake_wx.TE_MULTILINE = 4
    fake_wx.TE_READONLY = 8
    fake_wx.ID_NO = 5103
    fake_wx.ID_CANCEL = 5101
    fake_wx.WXK_ESCAPE = 27
    fake_wx.StaticText = _StaticText
    fake_wx.TextCtrl = _TextCtrl
    fake_wx.Button = _Button
    fake_wx.EVT_BUTTON = _EVT_BUTTON
    fake_wx.EVT_CHAR_HOOK = _EVT_CHAR_HOOK
    fake_wx.lib = fake_lib

    return fake_wx, fake_lib, fake_sc


def _load_host_key_dialog(monkeypatch):
    """Import HostKeyDialog with fake wx and return the class."""
    fake_wx, fake_lib, fake_sc = _make_wx_modules()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    monkeypatch.setitem(sys.modules, "wx.lib", fake_lib)
    monkeypatch.setitem(sys.modules, "wx.lib.sized_controls", fake_sc)
    _StaticText.created = []

    sys.modules.pop("portkeydrop.dialogs.host_key_dialog", None)
    mod = importlib.import_module("portkeydrop.dialogs.host_key_dialog")
    return mod.HostKeyDialog


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHostKeyDialogConstants:
    def test_reject_is_zero(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        assert dlg_cls.REJECT == 0

    def test_accept_once_is_one(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        assert dlg_cls.ACCEPT_ONCE == 1

    def test_accept_permanent_is_two(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        assert dlg_cls.ACCEPT_PERMANENT == 2


class TestHostKeyDialogInit:
    def test_security_text_contains_hostname(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "example.com", "ssh-rsa", "aa:bb:cc:dd")
        text = next(c for c in dlg._pane.children if isinstance(c, _TextCtrl))
        assert "example.com" in text.value

    def test_security_text_contains_key_type(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "host.test", "ecdsa-sha2-nistp256", "ff:ee:dd")
        text = next(c for c in dlg._pane.children if isinstance(c, _TextCtrl))
        assert "ecdsa-sha2-nistp256" in text.value

    def test_security_text_contains_fingerprint(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "host.test", "ssh-ed25519", "de:ad:be:ef")
        text = next(c for c in dlg._pane.children if isinstance(c, _TextCtrl))
        assert "de:ad:be:ef" in text.value

    def test_dialog_title_is_accessible_name(self, monkeypatch):
        # The dialog title (passed to super().__init__) is the accessible name
        # for screen readers. SetName() on a dialog is not AT-readable.
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "host.test", "ssh-ed25519", "de:ad:be:ef")
        assert dlg.title == "Unknown Host Key"

    def test_initial_focus_is_reject_button(self, monkeypatch):
        # Reject is the safest default: it must be the default button so
        # Enter key triggers rejection without the user needing to navigate.
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "host.test", "ssh-ed25519", "de:ad:be:ef")
        pane = dlg._pane
        btn_pane = next(c for c in pane.children if isinstance(c, _SizedPanel))
        buttons = [c for c in btn_pane.children if isinstance(c, _Button)]
        reject_btn = buttons[2]  # third button: Accept Permanently, Accept Once, Reject
        assert reject_btn._default is True

    def test_escape_rejects_dialog(self, monkeypatch):
        from types import SimpleNamespace

        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "host.test", "ssh-ed25519", "de:ad:be:ef")
        event, handler = next(bound for bound in dlg._bound if bound[0] is _EVT_CHAR_HOOK)
        _ = event

        def skip():
            return None

        key_event = SimpleNamespace(GetKeyCode=lambda: 27, Skip=skip)
        handler(key_event)
        assert dlg._modal_result == dlg_cls.REJECT

    def test_accept_permanent_button_bind(self, monkeypatch):
        """Line 35: Accept Permanently button binds a handler."""
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "example.com", "ssh-rsa", "aa:bb:cc")
        # Accept Permanently is the first button; verify it has a Bind
        pane = dlg._pane
        btn_pane = next(c for c in pane.children if isinstance(c, _SizedPanel))
        buttons = [c for c in btn_pane.children if isinstance(c, _Button)]
        accept_perm = buttons[0]
        assert len(accept_perm._bound) == 1, "Accept Permanently button should have one handler"

    def test_accept_permanent_handler_calls_end_modal(self, monkeypatch):
        """Invoking the Accept Permanently handler ends modal with ACCEPT_PERMANENT."""
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "example.com", "ssh-rsa", "aa:bb:cc")
        pane = dlg._pane
        btn_pane = next(c for c in pane.children if isinstance(c, _SizedPanel))
        buttons = [c for c in btn_pane.children if isinstance(c, _Button)]
        accept_perm = buttons[0]
        _event, handler = accept_perm._bound[0]
        handler(None)  # simulate button click
        assert dlg._modal_result == dlg_cls.ACCEPT_PERMANENT

    def test_all_three_buttons_bound(self, monkeypatch):
        dlg_cls = _load_host_key_dialog(monkeypatch)
        dlg = dlg_cls(None, "example.com", "ssh-rsa", "aa:bb:cc")
        pane = dlg._pane
        btn_pane = next(c for c in pane.children if isinstance(c, _SizedPanel))
        buttons = [c for c in btn_pane.children if isinstance(c, _Button)]
        assert len(buttons) == 3
        for btn in buttons:
            assert len(btn._bound) == 1
