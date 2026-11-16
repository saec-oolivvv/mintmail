; Installateur Windows de MintMail (Inno Setup 6). Appelé par build-windows.ps1 avec /DAppVersion /DAppDir /DOutDir.
[Setup]
AppId={{6B0E2C5A-7C0A-4C1E-9B0D-5A0E3D7A4F11}
AppName=MintMail
AppVersion={#AppVersion}
AppPublisher=SAEC
DefaultDirName={autopf}\MintMail
DefaultGroupName=MintMail
OutputDir={#OutDir}
OutputBaseFilename=MintMail-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\MintMail.exe

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\MintMail"; Filename: "{app}\MintMail.exe"
Name: "{autodesktop}\MintMail"; Filename: "{app}\MintMail.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Icône sur le Bureau"; Flags: unchecked

[Run]
Filename: "{app}\MintMail.exe"; Description: "Lancer MintMail"; Flags: nowait postinstall skipifsilent
