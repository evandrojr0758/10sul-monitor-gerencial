[Setup]
AppId={{17C2F95A-E918-43BD-BB6B-9C2EAF930A10}
AppName=10 Sul - Portal da Manutenção
AppVersion=1.0.0
AppPublisher=Evandro Junior
DefaultDirName={localappdata}\Programs\10SulManutencao
DefaultGroupName=10 Sul
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=Instalar_10Sul_Manutencao_Offline_1_0_0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\10SulManutencao.exe
CloseApplications=yes
[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: checkedonce
[Files]
Source: "dist\10SulManutencao.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIA_ME.txt"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Portal da Manutenção 10 Sul"; Filename: "{app}\10SulManutencao.exe"
Name: "{userdesktop}\Portal da Manutenção 10 Sul"; Filename: "{app}\10SulManutencao.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\10SulManutencao.exe"; Description: "Abrir Portal da Manutenção"; Flags: nowait postinstall skipifsilent
