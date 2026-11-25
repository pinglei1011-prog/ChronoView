#define AppVersion "1.0.0"
#define ProjectRoot AddBackslash(SourcePath) + ".."
[Setup]
AppId={{8A2E56B4-A023-4A20-A995-55C7707CF23D}
AppName=ChronoView
AppVersion={#AppVersion}
AppVerName=ChronoView V1.0 正式版
AppPublisher=ChronoView
AppPublisherURL=https://github.com/pinglei1011-prog/ChronoView
AppSupportURL=https://github.com/pinglei1011-prog/ChronoView/issues
DefaultDirName={localappdata}\Programs\ChronoView
DefaultGroupName=ChronoView
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
WizardStyle=modern
SetupIconFile={#ProjectRoot}\assets\chronoview.ico
UninstallDisplayIcon={app}\ChronoView.exe
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=ChronoView-{#AppVersion}-setup-win64
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\ChronoView-{#AppVersion}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{groupname}\ChronoView"; Filename: "{app}\ChronoView.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ChronoView"; Filename: "{app}\ChronoView.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ChronoView.exe"; Description: "启动 ChronoView"; Flags: nowait postinstall skipifsilent
