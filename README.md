# snapcraft

**macOS screenshot tool** — raccourci global, sélection de zone, éditeur d'annotation.

Appuie sur `Ctrl + Shift + X` pour déclencher la capture d'une région, puis annote avec des rectangles, flèches ou texte. Thème sombre, architecture native PyObjC.

> ⚠️ **En cours de développement** — l'éditeur d'annotation est partiellement fonctionnel. L'affichage de l'image capturée dans le canvas est un bug connu non résolu (canvas noir malgré le chargement correct de l'image). Le raccourci, la capture et l'architecture socket pré-chargé fonctionnent correctement.

---

## Fonctionnalités

- Raccourci global via Core Graphics event tap (`Ctrl + Shift + X`)
- Sélection de région interactive (`screencapture -i`)
- Éditeur d'annotation natif PyObjC (rectangles, flèches, texte en rouge)
- Undo/Redo (`Ctrl+Z` / `Ctrl+Shift+Z`)
- Ouverture instantanée via serveur socket pré-chargé
- Interface sombre sans barre de titre macOS
- Export : copier dans le presse-papiers et/ou enregistrer en PNG
- Bouton de fermeture (×) dans la toolbar

## Architecture

```
screenshot_tool.py   — démon principal (event tap, LaunchAgent)
editor.py            — éditeur d'annotation PyObjC (mode serveur ou standalone)
requirements.txt     — dépendances pip
```

Le démon tourne en arrière-plan via un `LaunchAgent` et pré-charge l'éditeur via un socket Unix (`/tmp/screenshot_editor.sock`) pour une ouverture quasi-instantanée.

## Prérequis

| Dépendance | Version |
|---|---|
| macOS | 12+ |
| Python | 3.12 (Homebrew, bundle Python.app) |
| PyObjC | ≥ 10.0 |
| Pillow | ≥ 10.0 |

> **Important** : utiliser le bundle `Python.app` de Homebrew (pas `/usr/bin/python3`) pour pouvoir ajouter Python dans les permissions Accessibilité sans blocage SIP.

## Installation

```bash
pip install -r requirements.txt
python3 screenshot_tool.py install
```

### Permission Accessibilité

Le raccourci global requiert la permission Accessibilité :

1. Ouvrir **Réglages Système → Confidentialité et sécurité → Accessibilité**
2. Ajouter le binaire Python.app de Homebrew :
   `/opt/homebrew/Cellar/python@3.12/<version>/Frameworks/Python.framework/Versions/3.12/Resources/Python.app`
3. Le LaunchAgent redémarre automatiquement

## Utilisation

```bash
# Installer le LaunchAgent (démarre automatiquement au login)
python3 screenshot_tool.py install

# Désinstaller
python3 screenshot_tool.py uninstall
```

Logs : `/tmp/screenshot_tool.log`

### Raccourcis dans l'éditeur

| Action | Raccourci |
|---|---|
| Undo | `Ctrl + Z` |
| Redo | `Ctrl + Shift + Z` |
| Valider texte | `Entrée` |
| Fermer | Bouton × (en haut à droite) |

### Boutons d'export

| Bouton | Action |
|---|---|
| Copier & Supprimer | Copie dans le presse-papiers, supprime le fichier PNG |
| Copier & Enregistrer | Copie dans le presse-papiers + conserve le PNG |
| Enregistrer | Enregistre le PNG sur le bureau |

## Bugs connus / En cours

- **Canvas noir** : `NSImage.drawInRect_`, `NSBitmapImageRep.drawInRect_` et `NSImageView` échouent tous silencieusement à afficher l'image dans la fenêtre borderless PyObjC. L'image se charge correctement (taille et objet valides), `drawRect_` est bien appelé, mais le rendu reste noir. Piste : Core Graphics / CALayer.
- **Boutons d'action** : positionnement vertical à vérifier après résolution du bug canvas.

## Dépannage

- **Le raccourci ne fonctionne pas** → vérifier la permission Accessibilité et `/tmp/screenshot_tool.log`
- **`CGEventTapCreate → None`** → le processus n'a pas la permission Accessibilité
- **`screencapture` introuvable** → vérifier que `/usr/sbin` est dans le PATH du LaunchAgent

## Licence

MIT
