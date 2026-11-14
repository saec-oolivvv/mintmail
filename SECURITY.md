# Sécurité de MintMail

## Signaler une faille

Écrivez à **contact@saec.me** : description, étapes pour reproduire, version (`mintmail --version`). Merci de ne pas publier le problème avant
qu'un correctif soit disponible. Seule la **dernière version** est maintenue.

## Ce que MintMail protège (modèle de menaces)

| Menace | Protection |
|---|---|
| E-mail piégé (HTML actif, pistage, hameçonnage technique) | HTML reconstruit par liste blanche, politique de sécurité de contenu (CSP), JavaScript désactivé dans le lecteur, images distantes bloquées, WebKit durci, contexte éphémère |
| Lien ou pièce jointe malveillants | Seuls http / https / mailto s'ouvrent ; programmes et scripts jamais ouverts ; fichiers à risque : confirmation |
| Autres comptes de la machine | Dossiers `0700`, fichiers `0600` (courrier, pièces jointes, réglages, journal) |
| Écoute / intrusion sur le réseau local | Synchronisation chiffrée + authentifiée, limitée au réseau local, délais et tables bornés, codes faibles refusés |
| Contenu hostile envoyé à l'IA | Aucune action sans validation, rendu échappé, brouillons jamais envoyés (mais un modèle peut être trompé : voir R4) |
| Serveurs mail | TLS avec vérification des certificats, STARTTLS obligatoire, OAuth avec PKCE |
| Mise à jour piégée (GitHub piraté, réseau hostile, paquet modifié) | Signature RSA / SHA-256 vérifiée avec une clé publique installée avec MintMail ; retour en arrière refusé ; installation par un programme administrateur minimal, mot de passe demandé (voir `docs/UPDATES.md`) |

## Rapport d'audit — version 1.10.2

**Méthode.** Revue manuelle du code (~15 000 lignes Python) selon les risques réels d'un client mail : HTML hostile, liens et fichiers, stockage
des secrets, réseau (synchronisation, désabonnement, OAuth, agenda), exécution de commandes, SQL, fichiers temporaires, installation. Chaque faille
trouvée a été corrigée **et** couverte par un test de régression (`tests/test_security.py` : 19 tests, dont 3 000 HTML aléatoires et 11 entrées
pathologiques, plus ~70 charges d'attaque classiques).
**Limites de l'audit** : pas de test d'intrusion sur de vrais systèmes, pas de fuzzing de l'analyse MIME / IMAP, pas d'audit des bibliothèques
tierces (GTK, WebKit, GdkPixbuf, Python), pas d'expertise cryptographique indépendante, interface Qt non testée automatiquement sur vrai écran.
**Cet audit ne prouve pas l'absence de faille.**

### Failles trouvées et corrigées

| # | Gravité | Problème | Correction |
|---|---|---|---|
| S1 | Élevée | Le nettoyeur HTML (expressions régulières) se contournait (`<scr<script>ipt>`, `<img/src=x/onerror=…>`, schémas obfusqués) ; la fenêtre de **rédaction exécute du JavaScript** : répondre à un message piégé pouvait exécuter du code et exfiltrer le texte écrit | Nettoyeur à **liste blanche** reconstruit par analyseur (`htmlsafe.py`), CSP de l'éditeur (seul son script, par empreinte), vue éphémère, liens validés |
| S2 | Élevée | Le lecteur affichait le HTML non nettoyé ; formulaires, redirections, cadres, `<base>`, `ping` : pistage et contournement du blocage des images | Nettoyage + CSP, politique de navigation (tout refusé sauf notre chargement), réglages WebKit durcis |
| S3 | Moyenne | Un lien cliqué ouvrait n'importe quel schéma (`file:`, `smb:`, gestionnaires d'applications) | http / https / mailto uniquement, adresse nettoyée des caractères de contrôle |
| S4 | Moyenne | Courrier (`cache.db`), pièces jointes, journal créés avec les droits par défaut (lisibles par les autres comptes) ; `config.json` passé en 0600 *après* écriture | Création directe en 0600 / 0700, remise en ordre au démarrage (anciennes installations comprises), état affiché par `--diagnose` |
| S5 | Moyenne | **Détournement par le dossier courant** : lancé depuis un dossier contenant un répertoire `mintmail/`, le programme exécutait ce code (démontré) | Lanceurs en mode isolé (`python3 -I`) |
| S6 | Moyenne | Synchronisation : connexions acceptées de toute adresse, pas de délai total (monopolisation des emplacements), ports d'annonce et tables non bornés, code faible accepté ; la première correction du délai ne coupait pas réellement la lecture bloquée (trouvé par test) | Réseau local / VPN / bouclage uniquement, délai total effectif (`shutdown`), ports 1024-65535, 64 pairs maximum, codes faibles refusés, nouveau générateur (~120 bits) |
| S7 | Moyenne | Désabonnement : requête vers n'importe quel hôte https (réseau interne, métadonnées cloud) et suivi des redirections ; `mailto:` multi-destinataires / Cc / Bcc issus de l'en-tête du message | Refus des adresses non publiques (y compris redirections), adresse mailto unique et valide |
| S8 | Moyenne | Pièces jointes : ouverture directe de scripts, exécutables, `.desktop`, SVG / HTML actifs ; astuces d'extension (double extension, point final, caractères bidirectionnels) | Programmes et scripts : enregistrement seulement ; fichiers à risque : confirmation ; SVG sans aperçu intégré ; images > 15 Mo sans aperçu |
| S9 | Faible | Noms de dossiers IMAP : caractères de contrôle non refusés (injection de commande) | Refus |
| S10 | Faible | Estimation de force du code : 2,9 % des codes produits par l'ancien bouton « Générer » étaient refusés (défaut de ma propre correction, trouvé par test) | Estimation ajustée, nouveau générateur toujours accepté ; ~0,5 % des anciens codes aléatoires déclenchent un avertissement (non bloquant) |

### Examiné, aucune faille trouvée

Requêtes SQL (paramétrées ; seules des constantes sont concaténées) · exécution de commandes (listes d'arguments, jamais de shell) ·
désérialisation (JSON uniquement, ni `pickle` ni `eval`) · TLS (vérification par défaut, STARTTLS obligatoire, pas de repli en clair) ·
comparaisons HMAC en temps constant · nonces, liaison de session et numéros de séquence de la synchronisation (octet altéré, mauvais code, rejeu :
rejetés) · OAuth (PKCE, état, boucle locale 127.0.0.1, HTTPS exigé) · noms de fichiers des pièces jointes (aucune traversée de dossier) ·
fichiers temporaires (`mkstemp`, 0600).

### Risques restants (non corrigés)

- **R1 — Cryptographie de la synchronisation « maison »** (HMAC-SHA256 en mode compteur) : aucun audit externe, pas de confidentialité persistante ;
  un code faible permet une attaque hors ligne sur un échange capturé. *Recommandation : audit cryptographique indépendant, ou remplacement par un
  protocole éprouvé (TLS-PSK, Noise, PAKE). N'utilisez la synchronisation que sur un réseau de confiance, avec le code généré.*
- **R2 — Confiance totale entre machines jumelées** : un pair compromis peut pousser des comptes, des adresses de serveur, la clé d'IA.
- **R3 — Secrets en clair dans `config.json` (0600)** quand aucun trousseau système n'est disponible (`--diagnose` le signale).
- **R4 — Injection de prompt** : un e-mail peut tromper un modèle (résumé, tri, classement faussés). Atténué : validation obligatoire, brouillons jamais envoyés.
- **R5 — DNS rebinding** (désabonnement) : l'adresse est vérifiée avant la requête, pas entre la résolution et la connexion.
- **R6 — Bibliothèques système** (Qt / QtWebEngine, Python) : surface héritée ; gardez le système à jour.
- **R7 — Lecteur QtWebEngine non testé sur écran par la batterie automatique** : JavaScript coupé, navigation interdite, liens filtrés ; l'HTML est de toute façon reconstruit par liste blanche. En cas de comportement inattendu, merci de le signaler.
- **R8 — Hameçonnage visuel** : MintMail n'avertit pas quand le texte d'un lien affiche une adresse différente de sa destination, et ne détecte pas
  les domaines imitant ceux d'un correspondant.
- **R9 — Hors périmètre** : un administrateur de la machine ou un logiciel malveillant du même compte lisent tout.

### Mises à jour automatiques (ajoutées en 1.11.0) — conception et risques propres

Voir `docs/UPDATES.md`. Contrôles testés (`tests/test_updater.py`, avec un faux GitHub local et de vraies signatures openssl) : signature d'une autre clé, paquet modifié d'un octet, signature d'un autre fichier,
signature vide ou absente, paquet qui n'est pas MintMail, version identique ou plus ancienne, lien symbolique ou fichier spécial à la place du paquet, fichier remplacé après vérification (l'installation utilise la
copie vérifiée), hôte ou redirection hors GitHub, brouillons et préversions, plafonds de taille, somme de contrôle fausse, clé de vérification modifiable par un non-administrateur.

- **R10 — Clé privée de signature** : sa compromission permettrait d'installer n'importe quel programme sur toutes les machines. Protégée par une phrase secrète, hors dépôt, jamais confiée à la CI. Un attaquant doit AUSSI avoir l'accès en écriture au dépôt GitHub pour publier. Sauvegarde contrôlée (`tools/backup-signing-key.sh`) et rotation planifiée sans réinstallation (`tools/rotate-signing-key.sh`, `tools/release.sh --rotation`) : voir docs/KEY-RECOVERY.md. Pas de révocation automatique (volontaire : elle ouvrirait un autre risque).
- **R11 — Attaque par gel** non détectée (empêcher d'apprendre une nouvelle version) ; une version intermédiaire authentique mais plus ancienne que la dernière peut être rejouée.
- **R12 — Non testé de bout en bout** sur un vrai GitHub ni avec une vraie fenêtre d'authentification polkit (testé : faux GitHub, vraies signatures, vrai `dpkg`).
