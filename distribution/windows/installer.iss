#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef BuildDir
  #error BuildDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif

[Setup]
AppId={{75337384-744F-48DD-A84C-880A41DF5A2A}
AppName=Planning & Scheduling
AppVersion={#AppVersion}
AppPublisher=MICHELIN
AppComments=Planning & Scheduling Michelin - Centro Operacional
DefaultDirName={localappdata}\Programs\Michelin\PlanningScheduling
DisableDirPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
DefaultGroupName=Planning & Scheduling
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Planning-Scheduling-Setup-{#AppVersion}
SetupIconFile={#BuildDir}\planning.ico
UninstallDisplayIcon={app}\PlanningScheduling.exe
WizardStyle=modern
WizardImageFile={#BuildDir}\wizard.bmp
WizardSmallImageFile={#BuildDir}\wizard-small.bmp
Compression=lzma2/fast
SolidCompression=yes
AppMutex=Local\Michelin.PlanningScheduling
CloseApplications=no
RestartApplications=no
UninstallDisplayName=Planning & Scheduling Michelin
DisableWelcomePage=no
LicenseFile={#PayloadDir}\DISTRIBUTION-NOTICE.txt

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
WelcomeLabel1=MICHELIN%nPlanning & Scheduling%nCentro Operacional
WelcomeLabel2=Este assistente instala o Planning & Scheduling neste computador.%n%nO aplicativo inclui os componentes necessarios. O acesso ao BMA e SharePoint utiliza sua propria autenticacao corporativa.

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\browser"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Planning & Scheduling"; Filename: "{app}\PlanningScheduling.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Planning & Scheduling"; Filename: "{app}\PlanningScheduling.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\PlanningScheduling.exe"; Description: "Abrir Planning & Scheduling"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
  InstalledPacked, SetupPacked: Int64;
begin
  Result := True;
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{75337384-744F-48DD-A84C-880A41DF5A2A}_is1',
    'DisplayVersion', InstalledVersion) then
  begin
    if StrToVersion(InstalledVersion, InstalledPacked) and
       StrToVersion('{#AppVersion}', SetupPacked) then
    begin
      if ComparePackedVersion(InstalledPacked, SetupPacked) > 0 then
      begin
        SuppressibleMsgBox('Uma versao mais recente do Planning & Scheduling ja esta instalada. Use o instalador atualizado.',
          mbError, MB_OK, IDOK);
        Result := False;
      end;
    end;
  end;
end;