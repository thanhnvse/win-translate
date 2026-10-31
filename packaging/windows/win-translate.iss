; Inno Setup script for the Windows installer. scripts/package.py compiles it
; after PyInstaller has frozen the app, passing:
;   /DAppVersion=<version>  /DSourceDir=<frozen win-translate folder>
;   /DIconFile=<win-translate.ico>
;
; A per-user install: no administrator prompt, into
; %LOCALAPPDATA%\Programs\win-translate, the way most tray utilities install.

#ifndef AppVersion
  #error AppVersion must be defined (/DAppVersion=...)
#endif
#ifndef SourceDir
  #error SourceDir must be defined (/DSourceDir=...)
#endif

#define AppName "win-translate"
#define AppExe "win-translate.exe"

[Setup]
; Fixed for good: it is how Windows recognises an upgrade of the same app.
AppId={{84C4D80A-EF88-55F7-9797-EE745A7270BF}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=thanhnvse
AppPublisherURL=https://github.com/thanhnvse/win-translate
AppSupportURL=https://github.com/thanhnvse/win-translate/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The app holds this mutex while it runs (wintranslate/app.py), so setup and
; uninstall can ask for it to be closed instead of failing on locked files.
AppMutex=Global\win-translate-single-instance
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "&Start {#AppName} when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent
