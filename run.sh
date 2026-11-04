#!/usr/bin/env bash
# Lance MintMail directement depuis ce dossier, sans installation.
cd "$(dirname "${BASH_SOURCE[0]}")" && exec python3 -m mintmail "$@"
