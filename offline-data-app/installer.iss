; Inno Setup Script for SOC Data Processor
; Requires Inno Setup 6.x (https://jrsoftware.org/isinfo.php)
;
; Build with: iscc installer.iss
; Or use build_installer.bat (recommended — auto-generates version.iss)
;
; Prerequisites: Run PyInstaller first to create dist\OfflineDataApp\

#define MyAppName "SOC Data Processor"
; Version is injected by build_installer.bat into version.iss
; If building manually, create version.iss with: #define MyAppVersion "1.0.0"
#include "version.iss"
#define MyAppPublisher "Your Organization"
#define MyAppExeName "OfflineDataApp.exe"
#define MyAppId "{{B4F7E2A1-8C3D-4F5E-9A1B-2C3D4E5F6A7B}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
; No admin required — installs per-user
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=SOCDataProcessor-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Allow upgrading over existing install
UsePreviousAppDir=yes
; Uninstall support
Uninstallable=yes
UninstallDisplayName={#MyAppName}
; Close running instance before install
CloseApplications=yes
RestartApplications=no
; Misc
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=
; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenu"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checked

[Files]
; Bundle the entire PyInstaller dist folder
Source: "dist\OfflineDataApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Option to launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up log files left behind
Type: files; Name: "{app}\app.log"
Type: files; Name: "{app}\app.log.*"

[Code]
// Close running instance before upgrading
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Try to kill any running instance silently
  Exec('taskkill', '/f /im {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;
