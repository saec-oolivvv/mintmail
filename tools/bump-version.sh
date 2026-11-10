#!/bin/sh
# Prépare une nouvelle version : met à jour VERSION et mintmail/VERSION et ajoute une section au CHANGELOG.md (à compléter avant de publier).
# Usage : tools/bump-version.sh 1.12.0
set -e
cd "$(dirname "$0")/.."
echo "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "Usage : $0 X.Y.Z (ex. 1.12.0)"; exit 1; }
NEW="$1"
OLD="$(cat VERSION)"
python3 - "$NEW" <<'PY'
import re, sys
new = sys.argv[1]
s = open("CHANGELOG.md", encoding="utf-8").read()
if re.search(r"^## %s\s*$" % re.escape(new), s, re.M):
    sys.exit("CHANGELOG.md contient déjà une section %s" % new)
open("CHANGELOG.md", "w", encoding="utf-8").write(s.replace("# Changelog\n\n", "# Changelog\n\n## %s\n- (à compléter)\n\n" % new, 1))
PY
echo "$NEW" > VERSION
echo "$NEW" > mintmail/VERSION
echo "Version $OLD -> $NEW. Complétez la section « $NEW » de CHANGELOG.md, enregistrez (git commit), puis lancez tools/release.sh"
