#!/bin/sh
# Capture guidée des écrans de docs/screenshots/README.md. Nécessite une session graphique et gnome-screenshot (ou ImageMagick « import »).
cd "$(dirname "$0")/../docs/screenshots" || exit 1
shot() {
    printf '\n>>> %s\n    Affichez cet écran dans MintMail puis appuyez sur Entrée (capture dans 5 s)... ' "$2"
    read -r _
    if command -v gnome-screenshot >/dev/null 2>&1; then gnome-screenshot -w -d 5 -f "$1"
    elif command -v import >/dev/null 2>&1; then sleep 5; import -window "$(xdotool getactivewindow 2>/dev/null || echo root)" "$1"
    else echo "Installez gnome-screenshot ou imagemagick."; exit 1; fi
    echo "    -> $1"
}
shot 01-boite-aurora.png "Boîte de réception, style Aurora sombre"
shot 02-boite-papier.png "Même vue, style Papier"
shot 03-boite-terminal.png "Même vue, style Terminal"
shot 04-lecteur-resume-ia.png "Message ouvert avec le résumé ✨"
shot 05-clic-droit-ia.png "Menu clic droit avec la section ✨ IA"
shot 06-assistant.png "Assistant IA (Ctrl+J) avec un plan d'actions"
shot 07-classement-ia.png "Proposition de classement dans des dossiers"
shot 08-aujourdhui.png "Page Aujourd'hui (touche T)"
shot 09-redaction.png "Rédaction avec menu IA et champ De"
shot 10-parametres-ia.png "Paramètres → IA"
shot 11-agenda-google.png "Paramètres → Agenda (Google / CalDAV)"
shot 12-aide.png "Aide intégrée (F1)"
echo "Terminé : vérifiez les images (aucune donnée personnelle visible) avant de les publier."
