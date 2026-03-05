from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import portkeydrop.screen_reader as sr


def test_try_import_backend_prefers_prism(monkeypatch):
    fake_prism = object()

    real_import = __import__

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "prism":
            return fake_prism
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=_imp):
        mod, name = sr._try_import_backend()

    assert mod is fake_prism
    assert name == "prism"


def test_try_import_backend_falls_back_to_prismatoid():
    fake_prismatoid = object()
    real_import = __import__

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "prism":
            raise ImportError("no prism")
        if name == "prismatoid":
            return fake_prismatoid
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=_imp):
        mod, name = sr._try_import_backend()

    assert mod is fake_prismatoid
    assert name == "prismatoid"


def test_announcer_uses_context_backend(monkeypatch):
    speak = MagicMock()
    backend = SimpleNamespace(name="nvda", speak=speak)

    class _Ctx:
        def acquire_best(self):
            return backend

    fake_mod = SimpleNamespace(Context=_Ctx)
    monkeypatch.setattr(sr, "_try_import_backend", lambda: (fake_mod, "prism"))

    ann = sr.ScreenReaderAnnouncer()
    ann.announce("hello")

    assert ann.is_available() is True
    speak.assert_called_once_with("hello")


def test_announcer_falls_back_to_module_speak(monkeypatch):
    speak = MagicMock()
    fake_mod = SimpleNamespace(speak=speak)
    monkeypatch.setattr(sr, "_try_import_backend", lambda: (fake_mod, "prismatoid"))

    ann = sr.ScreenReaderAnnouncer()
    ann.announce("test")

    assert ann.is_available() is True
    speak.assert_called_once_with("test")


def test_announcer_handles_missing_backend(monkeypatch):
    monkeypatch.setattr(sr, "_try_import_backend", lambda: (None, None))
    ann = sr.ScreenReaderAnnouncer()
    ann.announce("ignored")
    assert ann.is_available() is False


def test_announcer_handles_speak_exceptions(monkeypatch):
    def _boom(_text):
        raise RuntimeError("fail")

    fake_mod = SimpleNamespace(speak=_boom)
    monkeypatch.setattr(sr, "_try_import_backend", lambda: (fake_mod, "prism"))

    ann = sr.ScreenReaderAnnouncer()
    # Should not raise.
    ann.announce("hello")
