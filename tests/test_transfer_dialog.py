"""Tests for transfer dialog event binder helpers."""

from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


def test_notify_posts_event(transfer_module):
    module, fake_wx = transfer_module
    fake_wx.PostEvent.reset_mock()
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    window = MagicMock()
    manager = module.TransferManager(notify_window=window)

    manager._notify()

    fake_wx.PostEvent.assert_called_once()


def test_wx_event_binder_is_cached(transfer_module):
    module, fake_wx = transfer_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    binder1, event_type1 = module._get_wx_event_binder()
    binder2, event_type2 = module._get_wx_event_binder()

    assert binder1 == binder2
    assert event_type1 == event_type2
    assert fake_wx.NewEventType.call_count == 1


def test_get_transfer_event_binder_returns_shared_value(transfer_module):
    module, _ = transfer_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None

    binder = module.get_transfer_event_binder()

    assert binder is module._TRANSFER_EVENT_BINDER
