# Construit dist\MintMail-<version>-windows-x64.zip (application portable) et, si Inno Setup est installé, dist\MintMail-<version>-windows-x64-setup.exe.
# À lancer SUR WINDOWS (PowerShell) : Python 3.10+ requis ; pip télécharge PySide6 et PyInstaller. EXPÉRIMENTAL : non essayé par l'auteur sur une vraie machine Windows.
# L'application n'est pas signée : SmartScreen demande « Informations complémentaires → Exécuter quand même » au premier lancement.
$ErrorActionPreference = "Stop"
$Src = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Src
$Ver = (Get-Content VERSION -Raw).Trim()
$Out = Join-Path $Src "dist"; $Work = Join-Path $Out "windows-build"
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force -Path $Work | Out-Null
python -m venv "$Work\venv"
& "$Work\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$Work\venv\Scripts\python.exe" -m pip install --quiet PySide6 keyring certifi pyinstaller pillow
$Exc = @()
foreach ($m in "Qt3DAnimation Qt3DCore Qt3DExtras Qt3DInput Qt3DLogic Qt3DRender QtBluetooth QtCharts QtDataVisualization QtDesigner QtGraphs QtGraphsWidgets QtHelp QtHttpServer QtLocation QtMultimedia QtMultimediaWidgets QtNfc QtNetworkAuth QtQuick3D QtRemoteObjects QtScxml QtSensors QtSerialBus QtSerialPort QtSpatialAudio QtSql QtStateMachine QtTest QtTextToSpeech QtUiTools QtWebSockets".Split(" ")) { $Exc += "--exclude-module"; $Exc += "PySide6.$m" }
& "$Work\venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name MintMail --paths $Src `
    --collect-submodules mintmail --collect-data mintmail --hidden-import keyring.backends.Windows --hidden-import certifi --collect-data certifi `
    --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets --hidden-import PySide6.QtSvg @Exc `
    --distpath "$Work\dist" --workpath "$Work\build" --specpath $Work packaging\macos_main.py
$App = Join-Path $Work "dist\MintMail"
# fichiers de données du paquet (VERSION, langues, icônes) : sans VERSION l'application se croit en 1.0.0
$Pkg = Join-Path $App "_internal\mintmail"
New-Item -ItemType Directory -Force -Path $Pkg | Out-Null
foreach ($d in "VERSION", "locale", "icons") { if (-not (Test-Path (Join-Path $Pkg $d))) { Copy-Item -Recurse (Join-Path $Src "mintmail\$d") (Join-Path $Pkg $d) } }
if (-not (Test-Path (Join-Path $Pkg "VERSION"))) { throw "VERSION absent de l'application." }
$Zip = Join-Path $Out "MintMail-$Ver-windows-x64.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path "$App\*" -DestinationPath $Zip
(Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $Zip -Leaf) | Set-Content "$Zip.sha256"
Write-Host "construit : $Zip"
$Iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $Iscc) { $Iscc = Get-Item "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue }
if ($Iscc) {
    $IsccPath = if ($Iscc.Source) { $Iscc.Source } else { $Iscc.FullName }
    & $IsccPath "/DAppVersion=$Ver" "/DAppDir=$App" "/DOutDir=$Out" packaging\mintmail.iss
    $Setup = Join-Path $Out "MintMail-$Ver-windows-x64-setup.exe"
    if (Test-Path $Setup) { (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower() + "  " + (Split-Path $Setup -Leaf) | Set-Content "$Setup.sha256"; Write-Host "construit : $Setup" }
} else { Write-Host "Inno Setup absent : seul le .zip portable a été construit." }
