"""Tests for transfer dialog event binder helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


@pytest.fixture
def service_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.services.transfer_service", monkeypatch)
    return module, fake_wx


def test_notify_posts_event(service_module):
    module, fake_wx = service_module
    fake_wx.PostEvent.reset_mock()
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    window = MagicMock()
    svc = module.TransferService.__new__(module.TransferService)
    svc._notify_window = window
    svc._post_event()
    fake_wx.PostEvent.assert_called_once()


def test_wx_event_binder_is_cached(service_module):
    module, fake_wx = service_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    binder1, event_type1 = module._get_wx_event_binder()
    binder2, event_type2 = module._get_wx_event_binder()
    assert binder1 == binder2
    assert event_type1 == event_type2
    assert fake_wx.NewEventType.call_count == 1


def test_get_transfer_event_binder_returns_shared_value(service_module):
    module, _ = service_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    binder = module.get_transfer_event_binder()
    assert binder is module._TRANSFER_EVENT_BINDER


def _setup_dialog_wx(fake_wx):
    fake_wx.DEFAULT_DIALOG_STYLE = 0
    fake_wx.RESIZE_BORDER = 0
    fake_wx.CLOSE_BOX = 0
    fake_wx.ID_CLOSE = 999
    fake_wx.RIGHT = 0
    fake_wx.ALIGN_RIGHT = 0
    fake_wx.WXK_ESCAPE = 27
    fake_wx.VERTICAL = 0
    fake_wx.HORIZONTAL = 0

    class _Dialog:
        def __init__(self, parent, *args, **kwargs):
            self._parent = parent

        def Bind(self, *args, **kwargs):
            return None

        def SetSizer(self, *args, **kwargs):
            return None

        def SetName(self, *args, **kwargs):
            return None

        def Close(self):
            return None

        def Hide(self):
            return None

        def GetParent(self):
            return self._parent

        def Destroy(self):
            return None

    fake_wx.Dialog = _Dialog


def test_cancel_announces_filename_before_refresh(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = [
        SimpleNamespace(
            id="abc123",
            source="/remote/folder/report.csv",
            destination="/tmp/report.csv",
            direction=SimpleNamespace(value="download"),
            progress=0,
            status=module.TransferStatus.PENDING,
        )
    ]

    dialog = module.create_transfer_dialog(parent, service)
    dialog.GetParent = MagicMock(return_value=parent)
    dialog.transfer_list.GetFirstSelected.return_value = 0
    dialog._refresh = MagicMock()

    dialog._on_cancel(None)

    service.cancel.assert_called_once_with("abc123")
    parent._announce.assert_called_once_with("Cancelled transfer: report.csv")
    parent._update_status.assert_called_once_with("Cancelled transfer: report.csv", "")
    dialog._refresh.assert_called_once()


def test_cancel_announces_generic_message_when_filename_missing(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = [
        SimpleNamespace(
            id="def456",
            source="/",
            destination="/",
            direction=SimpleNamespace(value="download"),
            progress=0,
            status=module.TransferStatus.PENDING,
        )
    ]

    dialog = module.create_transfer_dialog(parent, service)
    dialog.GetParent = MagicMock(return_value=parent)
    dialog.transfer_list.GetFirstSelected.return_value = 0
    dialog._refresh = MagicMock()

    dialog._on_cancel(None)

    service.cancel.assert_called_once_with("def456")
    parent._announce.assert_called_once_with("Cancelled transfer.")
    parent._update_status.assert_called_once_with("Cancelled transfer.", "")
    dialog._refresh.assert_called_once()


def test_refresh_preserves_selected_transfer_when_list_updates(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)
    fake_wx.LIST_STATE_SELECTED = 1
    fake_wx.LIST_STATE_FOCUSED = 2

    parent = MagicMock()
    service = MagicMock()
    service.jobs = [
        SimpleNamespace(
            id="a1",
            source="/remote/a.txt",
            destination="/tmp/a.txt",
            direction=SimpleNamespace(value="download"),
            progress=10,
            status=module.TransferStatus.IN_PROGRESS,
        ),
        SimpleNamespace(
            id="a2",
            source="/remote/b.txt",
            destination="/tmp/b.txt",
            direction=SimpleNamespace(value="download"),
            progress=50,
            status=module.TransferStatus.IN_PROGRESS,
        ),
    ]

    dialog = module.create_transfer_dialog(parent, service)

    list_mock = MagicMock()
    list_mock.GetFirstSelected.return_value = 1
    list_mock.GetItemCount.side_effect = [0, 1]
    list_mock.InsertItem.side_effect = [0, 1]
    dialog.transfer_list = list_mock

    dialog._refresh()

    if list_mock.SetItemState.call_count:
        selected_rows = [c.args[0] for c in list_mock.SetItemState.call_args_list]
        assert 1 in selected_rows
    else:
        list_mock.Select.assert_called_once_with(1)


def test_get_selected_job_id_handles_non_int_selection(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = []
    dialog = module.create_transfer_dialog(parent, service)

    dialog.transfer_list.GetFirstSelected.return_value = object()
    assert dialog._get_selected_job_id() is None


def test_refresh_uses_select_fallback_without_set_item_state(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = [
        SimpleNamespace(
            id="b1",
            source="/remote/a.txt",
            destination="/tmp/a.txt",
            direction=SimpleNamespace(value="download"),
            progress=10,
            status=module.TransferStatus.IN_PROGRESS,
        )
    ]

    dialog = module.create_transfer_dialog(parent, service)
    list_mock = MagicMock()
    list_mock.GetFirstSelected.return_value = 0
    list_mock.GetItemCount.return_value = 0
    list_mock.InsertItem.return_value = 0
    dialog.transfer_list = list_mock

    dialog._refresh()

    list_mock.Select.assert_called_once_with(0)


def test_get_selected_job_id_returns_none_for_not_found(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)
    fake_wx.NOT_FOUND = -1

    parent = MagicMock()
    service = MagicMock()
    service.jobs = []
    dialog = module.create_transfer_dialog(parent, service)
    dialog.transfer_list.GetFirstSelected.return_value = -1

    assert dialog._get_selected_job_id() is None


def test_send_to_background_hides_dialog(transfer_module):
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = []

    dialog = module.create_transfer_dialog(parent, service)
    dialog.Hide = MagicMock()

    dialog._on_send_to_background(None)

    dialog.Hide.assert_called_once()


def test_close_dialog_does_not_cancel_any_job(transfer_module):
    """Acceptance: Closing the transfer dialog does not interrupt the transfer."""
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = [
        SimpleNamespace(
            id="running1",
            source="/remote/big.zip",
            destination="/tmp/big.zip",
            direction=SimpleNamespace(value="download"),
            progress=50,
            status=module.TransferStatus.IN_PROGRESS,
        )
    ]

    dialog = module.create_transfer_dialog(parent, service)
    dialog._timer = MagicMock()
    dialog.Destroy = MagicMock()

    dialog._on_close(None)

    # Service.cancel must NOT be called
    service.cancel.assert_not_called()
    dialog._timer.Stop.assert_called_once()


def test_close_dialog_clears_parent_reference(transfer_module):
    """After close, parent._transfer_dlg is set to None for re-creation."""
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    parent._transfer_dlg = "some_dialog"
    service = MagicMock()
    service.jobs = []

    dialog = module.create_transfer_dialog(parent, service)
    dialog._timer = MagicMock()
    dialog.Destroy = MagicMock()
    dialog.GetParent = MagicMock(return_value=parent)

    dialog._on_close(None)

    assert parent._transfer_dlg is None


def test_escape_key_closes_dialog(transfer_module):
    """Escape key should close (hide) the dialog, not cancel transfers."""
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = []

    dialog = module.create_transfer_dialog(parent, service)
    dialog.Close = MagicMock()

    event = MagicMock()
    event.GetKeyCode.return_value = fake_wx.WXK_ESCAPE
    dialog._on_key(event)

    dialog.Close.assert_called_once()
    service.cancel.assert_not_called()


def test_non_escape_key_skips(transfer_module):
    """Non-escape key should be passed through."""
    module, fake_wx = transfer_module
    _setup_dialog_wx(fake_wx)

    parent = MagicMock()
    service = MagicMock()
    service.jobs = []

    dialog = module.create_transfer_dialog(parent, service)
    dialog.Close = MagicMock()

    event = MagicMock()
    event.GetKeyCode.return_value = ord("A")
    dialog._on_key(event)

    dialog.Close.assert_not_called()
    event.Skip.assert_called_once()
