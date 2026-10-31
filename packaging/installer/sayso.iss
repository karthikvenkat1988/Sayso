; Inno Setup 6 script: per-user install, no admin rights. Build with:  ISCC /DAppVersion=0.1.0 packaging\installer\sayso.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Sayso"
#endif

[Setup]
AppId={{B6F0C3E2-52B7-4C55-9D5E-5A7505A7505A}
AppName=Sayso
AppVersion={#AppVersion}
AppPublisher=Sayso
DefaultDirName={localappdata}\Programs\Sayso
DefaultGroupName=Sayso
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=Sayso-{#AppVersion}-setup
SetupIconFile=..\..\assets\sayso.ico
UninstallDisplayIcon={app}\Sayso.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start Sayso when I sign in to Windows"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Sayso"; Filename: "{app}\Sayso.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Sayso"; \
  ValueData: """{app}\Sayso.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\Sayso.exe"; Description: "Start Sayso now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Sayso.exe"; Flags: runhidden; RunOnceId: "StopSayso"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dataDir, roaming: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    dataDir := ExpandConstant('{localappdata}\Sayso');
    roaming := ExpandConstant('{userappdata}\Sayso');
    if (DirExists(dataDir) or DirExists(roaming)) and (not UninstallSilent) then
      if MsgBox('Also delete your Sayso settings, history and downloaded models?', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(dataDir, True, True, True);
        DelTree(roaming, True, True, True);
      end;
  end;
end;
