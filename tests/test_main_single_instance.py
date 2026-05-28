from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_main_exits_without_starting_wx_when_mutex_is_owned(monkeypatch):
    from portkeydrop import main as main_module

    manager = MagicMock()
    manager.try_acquire_lock.return_value = False
    manager.request_existing_instance_show.return_value = True

    monkeypatch.setattr(main_module, "SingleInstanceManager", lambda: manager)
    monkeypatch.setitem(sys.modules, "wx", SimpleNamespace())

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    manager.request_existing_instance_show.assert_called_once()
