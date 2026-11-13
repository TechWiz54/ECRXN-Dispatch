; ECRXN Dispatch - Windows setup (Inno Setup 6). Built by build.ps1, which fills StageDir with the app,
; a private Python, its packages and ffmpeg.
;
; A fresh install asks for the port and admin login and writes .env. Running a newer setup over an
; existing install replaces the program files only: .env, var\ (database), log\ and static\audio\ are kept.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\build\windows\stage"
#endif
#ifndef OutDir
  #define OutDir "..\..\dist"
#endif

[Setup]
AppId={{6B3F2A4E-91C7-4E0B-8D5A-ECB1D2A0E5C3}
AppName=ECRXN Dispatch
AppVersion={#AppVersion}
AppVerName=ECRXN Dispatch {#AppVersion}
AppPublisher=East Coast Receiver Network
AppPublisherURL=https://ecrxn.com
AppSupportURL=https://github.com/TechWiz54/ECRXN-Dispatch
DefaultDirName={autopf}\ECRXN Dispatch
DefaultGroupName=ECRXN Dispatch
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=ECRXN-Dispatch-Setup-{#AppVersion}
SetupIconFile=ecrxn.ico
UninstallDisplayIcon={app}\windows\ecrxn.ico
UninstallDisplayName=ECRXN Dispatch
LicenseFile={#StageDir}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Tasks]
Name: firewall; Description: "Let other devices on the network open the dashboard (opens the port in Windows Firewall)"
Name: desktopicon; Description: "Put a shortcut to the dashboard on the desktop"; Flags: unchecked

[InstallDelete]
; old program files (never the data folders: var, log, static\audio, .env)
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\routes"
Type: filesandordirs; Name: "{app}\templates"
Type: filesandordirs; Name: "{app}\migrations"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\pydeps"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\static\css"
Type: filesandordirs; Name: "{app}\static\js"
Type: filesandordirs; Name: "{app}\static\img"
Type: filesandordirs; Name: "{app}\static\vendor"

[Dirs]
; so .env and the logs can be opened without "access denied"
Name: "{app}"; Permissions: users-modify
Name: "{app}\var"
Name: "{app}\log"
Name: "{app}\static\audio"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "ecrxn.ico"; DestDir: "{app}\windows"; Flags: ignoreversion; AfterInstall: WriteEnvIfNew

[INI]
Filename: "{app}\windows\ECRXN Dispatch.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{code:GetPort}/"

[Icons]
Name: "{group}\ECRXN Dispatch"; Filename: "{app}\windows\ECRXN Dispatch.url"; IconFilename: "{app}\windows\ecrxn.ico"
Name: "{group}\Restart ECRXN Dispatch"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\windows\service.ps1"" -Restart"; \
    IconFilename: "{app}\windows\ecrxn.ico"; Comment: "Restart after changing the settings"
Name: "{group}\Settings (.env)"; Filename: "{win}\notepad.exe"; Parameters: """{app}\.env"""
Name: "{group}\Logs"; Filename: "{app}\log"
Name: "{group}\Reset the admin password"; Filename: "{app}\python\python.exe"; Parameters: """{app}\serve.py"" --reset-password"; WorkingDir: "{app}"
Name: "{group}\Uninstall ECRXN Dispatch"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ECRXN Dispatch"; Filename: "{app}\windows\ECRXN Dispatch.url"; IconFilename: "{app}\windows\ecrxn.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\service.ps1"" -Install -Port {code:GetPort} {code:FirewallArg}"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Starting ECRXN Dispatch..."
Filename: "http://localhost:{code:GetPort}/"; Description: "Open the dashboard"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\windows\service.ps1"" -Uninstall"; \
    Flags: runhidden waituntilterminated; RunOnceId: "RemoveTask"

[Code]
var
  SettingsPage: TInputQueryWizardPage;
  NewEnv: Boolean;
  ExistingPort: String;

function EnvPath: String;
begin
  Result := ExpandConstant('{app}\.env');
end;

function RandomPassword: String;
var
  Chars: String;
  I: Integer;
begin
  Chars := 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  Result := '';
  for I := 1 to 14 do
    Result := Result + Chars[Random(Length(Chars)) + 1];
end;

{ PORT=... from an existing .env (upgrades keep their port) }
function ReadEnvPort: String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '9911';
  if LoadStringsFromFile(EnvPath, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos('PORT=', Trim(Lines[I])) = 1 then
        Result := Trim(Copy(Trim(Lines[I]), 6, 10));
end;

function GetPort(Param: String): String;
begin
  if NewEnv then
    Result := Trim(SettingsPage.Values[0])
  else
    Result := ExistingPort;
end;

function FirewallArg(Param: String): String;
begin
  if WizardIsTaskSelected('firewall') then Result := '-Firewall' else Result := '';
end;

{ This PC's network address, for the links in alerts }
function LanAddress: String;
var
  Tmp: String;
  Code: Integer;
  Lines: TArrayOfString;
begin
  Result := 'localhost';
  Tmp := ExpandConstant('{tmp}\lanip.txt');
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -Command "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq ''Up'' } | Select-Object -First 1).IPv4Address.IPAddress | Out-File -Encoding ascii ''' + Tmp + '''"',
      '', SW_HIDE, ewWaitUntilTerminated, Code) then
    if LoadStringsFromFile(Tmp, Lines) and (GetArrayLength(Lines) > 0) and (Trim(Lines[0]) <> '') then
      Result := Trim(Lines[0]);
end;

procedure InitializeWizard;
begin
  SettingsPage := CreateInputQueryPage(wpSelectTasks, 'Settings',
    'How ECRXN Dispatch should run',
    'You can change these later in the Settings (.env) shortcut. Write down the password: you log in with it.');
  SettingsPage.Add('Port:', False);
  SettingsPage.Add('Admin username:', False);
  SettingsPage.Add('Admin password (at least 8 characters):', False);
  SettingsPage.Add('Timezone (e.g. America/New_York, America/Chicago):', False);
  SettingsPage.Values[0] := '9911';
  SettingsPage.Values[1] := 'admin';
  SettingsPage.Values[2] := RandomPassword;
  SettingsPage.Values[3] := 'America/New_York';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = SettingsPage.ID then
  begin
    { an update: keep the existing settings }
    NewEnv := not FileExists(EnvPath);
    if not NewEnv then ExistingPort := ReadEnvPort;
    Result := not NewEnv;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  P: Integer;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    NewEnv := not FileExists(EnvPath);
    if not NewEnv then ExistingPort := ReadEnvPort;
  end;
  if CurPageID = SettingsPage.ID then
  begin
    P := StrToIntDef(Trim(SettingsPage.Values[0]), 0);
    if (P < 1) or (P > 65535) then
    begin
      MsgBox('The port must be a number from 1 to 65535.', mbError, MB_OK);
      Result := False;
    end
    else if Trim(SettingsPage.Values[1]) = '' then
    begin
      MsgBox('Enter an admin username.', mbError, MB_OK);
      Result := False;
    end
    else if Length(Trim(SettingsPage.Values[2])) < 8 then
    begin
      MsgBox('The password needs at least 8 characters.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure WriteEnv;
var
  Ip, Port, S: String;
begin
  Ip := LanAddress;
  Port := Trim(SettingsPage.Values[0]);
  S := '# ECRXN Dispatch settings. Restart ECRXN Dispatch after changing them (Start menu).' + #10 +
       '# Every setting is explained in .env.example.' + #10 + #10 +
       'LOG_LEVEL=2' + #10 +
       'TIMEZONE=' + Trim(SettingsPage.Values[3]) + #10 + #10 +
       '# The address people use to reach this computer (used in alert links)' + #10 +
       'BASE_URL=http://' + Ip + ':' + Port + #10 +
       'HOST=0.0.0.0' + #10 +
       'PORT=' + Port + #10 +
       'WEB_THREADS=8' + #10 +
       'WEB_TIMEOUT=60' + #10 + #10 +
       'SESSION_COOKIE_SECURE=False' + #10 +
       'SESSION_COOKIE_DOMAIN=' + Ip + #10 +
       'SESSION_COOKIE_NAME=icad_dispatch' + #10 +
       'SESSION_COOKIE_PATH=/' + #10 + #10 +
       'SQLITE_DATABASE_PATH=var/icad_dispatch.db' + #10 + #10 +
       '# Admin account, created on the first start only' + #10 +
       'ROOT_USERNAME=' + Trim(SettingsPage.Values[1]) + #10 +
       'ROOT_PASSWORD=' + Trim(SettingsPage.Values[2]) + #10;
  SaveStringToFile(EnvPath, S, False);
end;

{ runs while the files are copied, so .env exists before ECRXN Dispatch is started }
procedure WriteEnvIfNew;
begin
  if NewEnv and not FileExists(EnvPath) then
    WriteEnv;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssInstall then
  begin
    NewEnv := not FileExists(EnvPath);
    if not NewEnv then ExistingPort := ReadEnvPort;
    { stop the running copy before its files are replaced }
    if FileExists(ExpandConstant('{app}\windows\service.ps1')) then
      Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\windows\service.ps1') + '" -Stop',
        '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if NewEnv then
      WizardForm.FinishedLabel.Caption :=
        'ECRXN Dispatch is running and starts with Windows.' + #13#10 + #13#10 +
        'Dashboard:  http://localhost:' + GetPort('') + #13#10 +
        'Username:   ' + Trim(SettingsPage.Values[1]) + #13#10 +
        'Password:   ' + Trim(SettingsPage.Values[2]) + #13#10 + #13#10 +
        'Change the password after you log in. The Start menu has the dashboard, settings, logs and a restart shortcut.'
    else
      WizardForm.FinishedLabel.Caption :=
        'ECRXN Dispatch was updated and is running again. Your settings, systems, triggers and saved calls were kept.' + #13#10 + #13#10 +
        'Dashboard:  http://localhost:' + GetPort('');
  end;
end;
