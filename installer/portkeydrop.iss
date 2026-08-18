; Inno Setup Script for PortkeyDrop
; Creates a Windows installer with Start Menu and Desktop shortcuts
;
; Requirements:
;   - Inno Setup 6.0 or later (https://jrsoftware.org/isinfo.php)
;   - cargo build --release output staged in dist/PortkeyDrop_dir/
;
; Build:
;   iscc installer/portkeydrop.iss

#define MyAppName "PortkeyDrop"
; Version is read from dist/version.txt (written by CI from Cargo.toml), or passed
; on the command line with /DMyAppVersion.
; Fail the build if it is missing so installers never ship with stale metadata.
#ifndef MyAppVersion
  #define VersionFilePath AddBackslash(SourcePath) + "..\dist\version.txt"
  #if FileExists(VersionFilePath)
    #define MyAppVersion ReadIni(VersionFilePath, "version", "value", "")
  #else
    #error Missing dist/version.txt; write it from Cargo.toml, or pass /DMyAppVersion, before compiling the installer.
  #endif
#endif
#define MyAppPublisher "Orinks"
#define MyAppURL "https://github.com/Orinks/PortkeyDrop"
#define MyAppExeName "PortkeyDrop.exe"
#define MyAppDescription "An accessible file transfer client for FTP, SFTP, FTPS, SCP, and WebDAV"

[Setup]
; Application identity
AppId={{A1F3E9C2-7B4D-4A8F-9E2D-3C5B8A1D7F4E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppComments={#MyAppDescription}

; Installation settings
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes

; Output settings
OutputDir=..\dist
OutputBaseFilename=PortkeyDrop_Setup_v{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

; Privileges and install scope
PrivilegesRequired=lowest
UsePreviousPrivileges=yes
PrivilegesRequiredOverridesAllowed=commandline

; Modern installer appearance
WizardStyle=modern
WizardSizePercent=100

; Windows version requirements
MinVersion=10.0

; Uninstaller settings
UninstallDisplayName={#MyAppName}
CreateUninstallRegKey=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files from Nuitka directory output
Source: "..\dist\PortkeyDrop_dir\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Fallback: if single-file exe exists, use that
; Source: "..\dist\PortkeyDrop.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcuts
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "{#MyAppDescription}"

; Quick Launch shortcut (optional, legacy)
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; Option to launch after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Register application path
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey

[Code]
const
  RunningAppImageName = 'PortkeyDrop.exe';
  UninstallKeyWithBraces = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A1F3E9C2-7B4D-4A8F-9E2D-3C5B8A1D7F4E}_is1';
  UninstallKeyWithoutBraces = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\A1F3E9C2-7B4D-4A8F-9E2D-3C5B8A1D7F4E_is1';

function IsPortkeyDropRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec(
    ExpandConstant('{cmd}'),
    '/C tasklist /FI "IMAGENAME eq ' + RunningAppImageName + '" /NH | find /I "' + RunningAppImageName + '" >nul',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    Result := ResultCode = 0
  else
    Log('Could not query running PortkeyDrop processes.');
end;

procedure KillPortkeyDrop(Force: Boolean);
var
  ResultCode: Integer;
  Parameters: String;
begin
  Parameters := '/IM ' + RunningAppImageName + ' /T';
  if Force then
    Parameters := '/F ' + Parameters;

  if Exec(
    ExpandConstant('{sys}\taskkill.exe'),
    Parameters,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    Log('taskkill.exe ' + Parameters + ' exited with code ' + IntToStr(ResultCode))
  else
    Log('Could not run taskkill.exe ' + Parameters);
end;

procedure WaitForPortkeyDropToExit(MaxWaitMilliseconds: Integer);
var
  WaitedMilliseconds: Integer;
begin
  WaitedMilliseconds := 0;
  while (WaitedMilliseconds < MaxWaitMilliseconds) and IsPortkeyDropRunning() do
  begin
    Sleep(500);
    WaitedMilliseconds := WaitedMilliseconds + 500;
  end;
end;

function CloseRunningPortkeyDrop(): Boolean;
begin
  Result := True;
  if not IsPortkeyDropRunning() then
    exit;

  Log('PortkeyDrop is running; requesting shutdown before install.');
  KillPortkeyDrop(False);
  WaitForPortkeyDropToExit(5000);

  if IsPortkeyDropRunning() then
  begin
    Log('PortkeyDrop is still running; force-stopping before install.');
    KillPortkeyDrop(True);
    WaitForPortkeyDropToExit(5000);
  end;

  Result := not IsPortkeyDropRunning();
  if not Result then
    Log('PortkeyDrop is still running after automatic close attempts.');
end;

procedure RemoveStalePerUserArpEntriesForAdminInstall();
begin
  if not IsAdminInstallMode then
    exit;

  if RegKeyExists(HKCU, UninstallKeyWithBraces) then
  begin
    if RegDeleteKeyIncludingSubkeys(HKCU, UninstallKeyWithBraces) then
      Log('Removed stale HKCU uninstall key: ' + UninstallKeyWithBraces)
    else
      Log('Failed to remove HKCU uninstall key: ' + UninstallKeyWithBraces);
  end;

  if RegKeyExists(HKCU, UninstallKeyWithoutBraces) then
  begin
    if RegDeleteKeyIncludingSubkeys(HKCU, UninstallKeyWithoutBraces) then
      Log('Removed stale HKCU uninstall key: ' + UninstallKeyWithoutBraces)
    else
      Log('Failed to remove HKCU uninstall key: ' + UninstallKeyWithoutBraces);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CloseRunningPortkeyDrop() then
    Result := 'Setup could not close Portkey Drop automatically. Please close it and run setup again.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    RemoveStalePerUserArpEntriesForAdminInstall();

  if CurStep = ssPostInstall then
  begin
    // Post-installation tasks
  end;
end;

[UninstallDelete]
; Clean up any cached files
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.pyc"
Type: dirifempty; Name: "{app}\__pycache__"
