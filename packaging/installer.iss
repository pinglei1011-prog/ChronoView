; Stage-four installer recipe. Requires a built dist\ChronoView and Inno Setup 6.
; This recipe is provided for future release work, not a verified installer build.
#define AppName "ChronoView"
#define AppVersion "0.1.0"

[Setup]
AppId={{54A91666-82B0-42C7-8347-1E858CAB834F}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ChronoView-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ChronoView.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\ChronoView\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ChronoView"; Filename: "{app}\ChronoView.exe"
Name: "{autodesktop}\ChronoView"; Filename: "{app}\ChronoView.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ChronoView.exe"; Description: "Launch ChronoView"; Flags: nowait postinstall skipifsilent
