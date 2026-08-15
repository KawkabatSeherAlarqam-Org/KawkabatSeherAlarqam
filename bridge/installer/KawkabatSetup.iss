#pragma code page 65001
; This file is saved as UTF-8 without a BOM -- the pragma above tells the
; Inno Setup compiler that explicitly, since without it (or a BOM) ISCC
; falls back to the system ANSI codepage and mangles the Arabic MsgBox
; strings in [Code] below.
;
; Inno Setup script for the Kawkabat MT5 Bridge installer (Phase 2).
;
; Installs bridge/build/dist/KawkabatBridge/ (the --onedir build from Phase 1)
; into %LOCALAPPDATA%\Kawkabat\KawkabatBridge\, ships the three autostart
; PowerShell scripts alongside it, registers the same logon-time scheduled
; task used in dev (via install-autostart.ps1 -ExePath ...), and starts it
; immediately so the bridge is reachable with no manual step after install.
;
; PrivilegesRequired=lowest throughout, on purpose: {localappdata} is always
; writable by the current user, and install-autostart.ps1's scheduled task
; (LogonType S4U, RunLevel Limited) was already verified to register without
; admin rights -- this installer must never need elevation.
;
; Build with build-installer.ps1 (wraps ISCC.exe on this file) after running
; bridge/build/build.ps1 first -- this script only packages an existing
; bridge/build/dist/KawkabatBridge/, it does not build it.

#define MyAppName "Kawkabat MT5 Bridge"
#define MyAppVersion "2.1.0"
#define BridgeRoot SourcePath + "\.."

[Setup]
AppId={{9BEB34CC-FFC2-4A95-A995-8B423FDBD13E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Kawkabat
DefaultDirName={localappdata}\Kawkabat
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourcePath}\dist
OutputBaseFilename=KawkabatSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\KawkabatBridge\KawkabatBridge.exe

[Files]
; The --onedir build (KawkabatBridge.exe + its _internal\ dependencies) --
; the exe alone will not run without _internal\ next to it, so the whole
; tree is copied recursively.
Source: "{#BridgeRoot}\build\dist\KawkabatBridge\*"; DestDir: "{app}\KawkabatBridge"; Flags: recursesubdirs createallsubdirs ignoreversion

; The autostart scripts must exist on the target machine long-term --
; run-bridge-supervised.ps1 is what the scheduled task invokes at every
; logon, referenced by this installed path, not the dev repo's.
Source: "{#BridgeRoot}\install-autostart.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#BridgeRoot}\uninstall-autostart.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#BridgeRoot}\run-bridge-supervised.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[UninstallDelete]
; run-bridge-supervised.ps1 writes its own supervisor.log relative to its own
; location ({app}\scripts\logs\), separate from the app's bridge-YYYY-MM-DD.log
; in {app}\logs\ -- created at runtime, so Inno doesn't track it automatically
; the way it does installed [Files]. Explicitly removed here so uninstall
; doesn't leave it behind; the app's own {app}\logs\ and executed.json/
; signal.json are NOT listed here on purpose and must never be added --
; those are the ones this installer is required to preserve.
Type: filesandordirs; Name: "{app}\scripts\logs"

[Code]

function RunHiddenPowerShell(const ScriptArgs: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass ' + ScriptArgs,
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function DirHasTerminal(const Dir: String): Boolean;
begin
  Result := FileExists(Dir + '\terminal64.exe');
end;

// Best-effort, installer-time-only heuristic for the "MT5 not found" notice
// -- NOT the real discovery logic (that lives in mt5_bridge.py's
// find_terminal_path() and runs at bridge startup). Only used to decide
// whether to show an informational message; never blocks installation.
function ScanForTerminal(const Root: String): Boolean;
var
  FindRec: TFindRec;
  Candidate, UpperName: String;
begin
  Result := False;
  if not DirExists(Root) then Exit;
  if FindFirst(Root + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
           (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          UpperName := Uppercase(FindRec.Name);
          if (Pos('METATRADER', UpperName) > 0) or (Pos('MT5', UpperName) > 0) then
          begin
            Candidate := Root + '\' + FindRec.Name;
            if DirHasTerminal(Candidate) then
            begin
              Result := True;
              Break;
            end;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function ScanAppDataMetaQuotes(): Boolean;
var
  Root: String;
  FindRec: TFindRec;
begin
  Result := False;
  Root := ExpandConstant('{userappdata}') + '\MetaQuotes\Terminal';
  if not DirExists(Root) then Exit;
  if FindFirst(Root + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
           (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          if FileExists(Root + '\' + FindRec.Name + '\terminal64.exe') then
          begin
            Result := True;
            Break;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function DetectMT5(): Boolean;
begin
  Result :=
    DirHasTerminal(ExpandConstant('{pf}') + '\MetaTrader 5') or
    DirHasTerminal(ExpandConstant('{pf32}') + '\MetaTrader 5') or
    ScanForTerminal(ExpandConstant('{pf}')) or
    ScanForTerminal(ExpandConstant('{pf32}')) or
    ScanAppDataMetaQuotes();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ExePath, ScriptsDir: String;
begin
  if CurStep = ssInstall then
  begin
    // Reinstall/upgrade over a running bridge: stop the task and kill the
    // process first, or the file copy below fails on locked .exe/.dll files.
    RunHiddenPowerShell(
      '-Command "Stop-ScheduledTask -TaskName ''KawkabatMT5Bridge'' -ErrorAction SilentlyContinue; ' +
      'Get-Process -Name KawkabatBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"',
      ResultCode);
    Sleep(1000); // let the OS release file handles after the forced kill
  end;

  if CurStep = ssPostInstall then
  begin
    ScriptsDir := ExpandConstant('{app}\scripts');
    ExePath := ExpandConstant('{app}\KawkabatBridge\KawkabatBridge.exe');

    if RunHiddenPowerShell(
         '-File "' + ScriptsDir + '\install-autostart.ps1" -ExePath "' + ExePath + '"',
         ResultCode) and (ResultCode = 0) then
    begin
      // The scheduled task only fires at the NEXT logon by default -- start
      // it now so /health is reachable immediately, with no manual step.
      RunHiddenPowerShell(
        '-Command "Start-ScheduledTask -TaskName ''KawkabatMT5Bridge'' -ErrorAction SilentlyContinue"',
        ResultCode);
    end
    else
    begin
      MsgBox(
        'تم تثبيت ملفات الجسر بنجاح، لكن تعذّر تسجيل التشغيل التلقائي (كود الخطأ: ' +
        IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
        'يمكنك تسجيله يدوياً لاحقاً بتشغيل:' + #13#10 +
        ScriptsDir + '\install-autostart.ps1',
        mbError, MB_OK);
    end;

    if not DetectMT5() then
      MsgBox(
        'تم تثبيت الجسر بنجاح، لكن لم يُعثر على تيرمينال MetaTrader 5 مثبَّتاً على هذا الجهاز.' + #13#10 + #13#10 +
        'الجسر سيكتشفه تلقائياً بمجرد تثبيته لاحقاً وإعادة تشغيله. إن كان مثبَّتاً في مسار غير معتاد، ' +
        'اضبط متغيّر البيئة KAWKABAT_MT5_PATH يدوياً إلى المسار الكامل لـ terminal64.exe.',
        mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  ScriptsDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Runs BEFORE Inno removes any files below -- uninstall-autostart.ps1
    // must still exist on disk at this point. -StopRunning makes it also
    // stop the running task instance and kill the supervisor/bridge
    // processes (its default, dev-workflow behavior deliberately leaves a
    // running instance alone -- wrong here, since this uninstall is about
    // to delete the files those processes depend on).
    ScriptsDir := ExpandConstant('{app}\scripts');
    if FileExists(ScriptsDir + '\uninstall-autostart.ps1') then
      RunHiddenPowerShell('-File "' + ScriptsDir + '\uninstall-autostart.ps1" -StopRunning', ResultCode);
    // Belt-and-suspenders: catches a bridge process started some other way
    // (manually, not via the scheduled task) that -StopRunning above cannot
    // know about.
    RunHiddenPowerShell(
      '-Command "Get-Process -Name KawkabatBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"',
      ResultCode);
    Sleep(1000);
  end;
end;
