"""Accessibility contracts for wx dialog controls."""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")

from portkeydrop.dialogs.properties import PropertiesDialog  # noqa: E402
from portkeydrop.dialogs.quick_connect import QuickConnectDialog  # noqa: E402
from portkeydrop.dialogs.site_manager import SiteManagerDialog  # noqa: E402
from portkeydrop.dialogs.transfer import TransferManager, create_transfer_dialog  # noqa: E402
from portkeydrop.protocols import RemoteFile  # noqa: E402
from portkeydrop.sites import SiteManager  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    app = wx.App.Get() or wx.App(False)
    yield app


def _assert_labeled_by(static_text: wx.StaticText, control: wx.Window) -> None:
    if hasattr(static_text, "GetLabelFor"):
        assert static_text.GetLabelFor() == control.GetId()


def test_quick_connect_dialog_accessibility_contracts(wx_app):
    dlg = QuickConnectDialog(None)

    assert dlg.host_text.HasFocus()
    assert dlg.protocol_choice.GetName() == "Protocol"
    assert dlg.host_text.GetName() == "Host"
    assert dlg.port_text.GetName() == "Port"
    assert dlg.username_text.GetName() == "Username"
    assert dlg.password_text.GetName() == "Password"

    labels = [w for w in dlg.GetChildren() if isinstance(w, wx.StaticText)]
    host_label = next(lbl for lbl in labels if lbl.GetLabelText() == "&Host:")
    _assert_labeled_by(host_label, dlg.host_text)

    dlg.Destroy()


def test_site_manager_dialog_accessibility_contracts(wx_app):
    dlg = SiteManagerDialog(None, SiteManager())

    assert dlg.site_list.HasFocus()
    assert dlg.site_list.GetName() == "Saved Sites"
    assert dlg.add_btn.GetName() == "Add Site"
    assert dlg.remove_btn.GetName() == "Remove Site"
    assert dlg.connect_btn.GetName() == "Connect Site"
    assert dlg.save_btn.GetName() == "Save Site"
    assert dlg.browse_btn.GetName() == "Browse Key Path"

    labels = [w for w in dlg.GetChildren() if isinstance(w, wx.StaticText)]
    host_label = next(lbl for lbl in labels if lbl.GetLabelText() == "&Host:")
    _assert_labeled_by(host_label, dlg.host_text)

    dlg.Destroy()


def test_properties_dialog_accessibility_contracts(wx_app):
    remote = RemoteFile(name="foo.txt", path="/tmp/foo.txt", size=123)
    dlg = PropertiesDialog(None, remote)

    name_field = next(
        child
        for child in dlg.GetChildren()
        if isinstance(child, wx.TextCtrl) and child.GetName() == "Name"
    )
    assert name_field.GetValue() == "foo.txt"

    ok_btn = dlg.FindWindowById(wx.ID_OK)
    assert ok_btn is not None
    assert ok_btn.GetName() == "Close File Properties"

    labels = [w for w in dlg.GetChildren() if isinstance(w, wx.StaticText)]
    name_label = next(lbl for lbl in labels if lbl.GetLabelText() == "Name:")
    _assert_labeled_by(name_label, name_field)

    dlg.Destroy()


def test_transfer_dialog_accessibility_contracts(wx_app):
    dlg = create_transfer_dialog(None, TransferManager())

    assert dlg.transfer_list.HasFocus()
    assert dlg.transfer_list.GetName() == "Transfer Queue"
    assert dlg.cancel_btn.GetName() == "Cancel Selected Transfer"
    assert dlg.close_btn.GetName() == "Close Transfer Queue"

    dlg.Destroy()
