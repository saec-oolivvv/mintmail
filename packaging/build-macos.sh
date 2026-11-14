#!/bin/sh
# Construit dist/MintMail-<version>-macos.dmg (à lancer SUR UN MAC : Python 3.10+ requis ; pip télécharge PySide6 et PyInstaller).
# Usage : packaging/build-macos.sh          L'application n'est pas signée par Apple : au premier lancement, clic droit → Ouvrir.
set -e
[ "$(uname)" = "Darwin" ] || { echo "Ce script se lance sur macOS."; exit 1; }
SRC=$(cd "$(dirname "$0")/.." && pwd)
cd "$SRC"
VER=$(tr -d '[:space:]' < VERSION)
OUT="$SRC/dist"; WORK="$OUT/macos-build"
rm -rf "$WORK" && mkdir -p "$WORK"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
"$WORK/venv/bin/pip" install --quiet PySide6 keyring certifi pyinstaller pillow
# icône : le SVG du paquet est rendu en PNG par Qt, puis converti en .icns par iconutil (échec = application sans icône personnalisée)
ICON_ARG=""
if "$WORK/venv/bin/python" - "$SRC/mintmail/icons/mintmail.svg" "$WORK/icon.iconset" <<'PY'
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication([])
svg, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
r = QSvgRenderer(svg)
for base in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = base * scale
        img = QImage(px, px, QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img); r.render(p); p.end()
        img.save(os.path.join(out, "icon_%dx%d%s.png" % (base, base, "@2x" if scale == 2 else "")))
PY
then iconutil -c icns "$WORK/icon.iconset" -o "$WORK/MintMail.icns" && ICON_ARG="--icon $WORK/MintMail.icns" || true; fi
# On n'embarque QUE les modules Qt utilisés (--collect-all PySide6 emportait tout Qt : Assistant, Designer, 3D… — 2 Go et une signature impossible)
EXC=""
for m in Qt3DAnimation Qt3DCore Qt3DExtras Qt3DInput Qt3DLogic Qt3DRender QtBluetooth QtCharts QtDataVisualization QtDesigner QtGraphs QtGraphsWidgets QtHelp \
         QtHttpServer QtLocation QtMultimedia QtMultimediaWidgets QtNfc QtNetworkAuth QtQuick3D QtRemoteObjects QtScxml QtSensors QtSerialBus QtSerialPort \
         QtSpatialAudio QtSql QtStateMachine QtTest QtTextToSpeech QtUiTools QtWebSockets; do EXC="$EXC --exclude-module PySide6.$m"; done
"$WORK/venv/bin/pyinstaller" --noconfirm --clean --windowed --name MintMail $ICON_ARG \
    --osx-bundle-identifier me.saec.mintmail --paths "$SRC" \
    --collect-submodules mintmail --collect-data mintmail --hidden-import keyring.backends.macOS --hidden-import certifi --collect-data certifi \
    --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets --hidden-import PySide6.QtSvg \
    --hidden-import PySide6.QtWebEngineCore --hidden-import PySide6.QtWebEngineWidgets $EXC \
    --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK" packaging/macos_main.py
APP="$WORK/dist/MintMail.app"
# numéro de version visible dans le Finder (« Lire les informations ») : PyInstaller met « 0.0.0 » par défaut
for KEY in CFBundleShortVersionString CFBundleVersion; do
    /usr/libexec/PlistBuddy -c "Set :$KEY $VER" "$APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :$KEY string $VER" "$APP/Contents/Info.plist"
done
codesign --force --deep --sign - "$APP" || echo "avertissement : signature ad hoc impossible (l'application se lancera quand même avec clic droit → Ouvrir)"        # signature « ad hoc » : nécessaire pour démarrer sur les Mac Apple Silicon (ce n'est pas une signature Apple)
STAGE="$WORK/dmg"; mkdir -p "$STAGE" && cp -R "$APP" "$STAGE/" && ln -s /Applications "$STAGE/Applications"
case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=x86_64 ;; esac
DMG="$OUT/MintMail-$VER-macos-$ARCH.dmg"        # le nom est celui que la mise à jour intégrée cherche dans la Release
rm -f "$DMG"
for TRY in 1 2 3; do                              # hdiutil échoue parfois (« Ressource occupée ») sur les machines de GitHub : on réessaie
    hdiutil create -volname "MintMail $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null && break
    echo "hdiutil : essai $TRY échoué"; rm -f "$DMG"; sleep 5
done
[ -f "$DMG" ] || { echo "Échec : image disque non créée."; exit 1; }
( cd "$OUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256" )     # vérifié par la mise à jour intégrée
echo "construit : $DMG"
