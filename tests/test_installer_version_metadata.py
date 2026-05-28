from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_inno_installer_closes_running_portkeydrop_instead_of_prompting() -> None:
    script = (ROOT / "installer" / "portkeydrop.iss").read_text(encoding="utf-8")

    assert "AppMutex=" not in script
    assert "CloseRunningPortkeyDrop" in script
    assert "WaitForPortkeyDropToExit" in script
    assert "taskkill.exe" in script
    assert "Parameters := '/IM ' + RunningAppImageName + ' /T';" in script
    assert "Parameters := '/F ' + Parameters;" in script
    assert "Setup could not close Portkey Drop automatically" in script


def test_inno_installer_has_no_stale_version_fallback() -> None:
    script = (ROOT / "installer" / "portkeydrop.iss").read_text(encoding="utf-8")

    assert "0.1.0" not in script
    assert "Missing dist/version.txt" in script
    assert "AddBackslash(SourcePath)" in script
    assert "ReadIni(VersionFilePath" in script


def test_inno_installer_keeps_previous_install_scope() -> None:
    script = (ROOT / "installer" / "portkeydrop.iss").read_text(encoding="utf-8")

    assert "UsePreviousPrivileges=yes" in script
    assert "PrivilegesRequiredOverridesAllowed=commandline" in script
    assert "PrivilegesRequiredOverridesAllowed=dialog" not in script
    assert "RemoveStalePerUserArpEntriesForAdminInstall" in script
