# Wind Updates Bot 🌊⛵

Bot Telegram qui envoie des notifications push quand de nouveaux runs de modèles météorologiques sont disponibles.

## Fonctionnalités

- **Notifications push** : Reçois une alerte dès qu'un nouveau run est calculé et publié
- **4 modèles supportés** : AROME, ARPEGE, GFS, ECMWF
- **Personnalisation** : Choisis les modèles et les heures de run qui t'intéressent
- **Consultation** : Vérifie à tout moment les derniers runs disponibles
- **Cache intelligent** : Limite les requêtes API (cache 5 min)

## Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/start` | S'inscrire au bot |
| `/models` | Choisir les modèles météo à suivre |
| `/runs` | Choisir les heures de run (00h, 06h, 12h, 18h) |
| `/status` | Voir ses abonnements actuels |
| `/lastruns` | Afficher les derniers runs disponibles |
| `/stop` | Se désabonner des notifications |
| `/help` | Afficher l'aide |

## Modèles météo supportés

| Modèle | Source | Résolution | Zone | Runs |
|--------|--------|------------|------|------|
| **AROME** | Météo-France | 1.3 km | France | 00h, 03h, 06h, 12h, 18h |
| **ARPEGE** | Météo-France | 0.1° | Europe/Monde | 00h, 06h, 12h, 18h |
| **GFS** | NOAA | 0.25° | Monde | 00h, 06h, 12h, 18h |
| **ECMWF** | Centre Européen | 0.25° | Monde | 00h, 06h, 12h, 18h |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   SOURCES MÉTÉO                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ Météo-France│  │    ECMWF     │  │   NOAA    │  │
│  │  (API WMS)  │  │ (opendata)   │  │ (NOMADS)  │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  │
└─────────┼────────────────┼──────────────────┼───────┘
          │                │                  │
          └────────────────┼──────────────────┘
                           │
                   ┌───────▼────────┐
                   │  Bot Python    │
                   │  sur Railway   │
                   │                │
                   │ • Scheduler    │◄── Vérifie toutes les 15 min
                   │ • Cache 5 min  │
                   │ • Notificateur │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │    SQLite      │
                   │                │
                   │ • Users        │
                   │ • Préférences  │
                   │ • Last runs    │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Telegram API  │
                   └───────┬────────┘
                           │
                   ┌───────▼────────┐
                   │  Utilisateurs  │
                   │  (push notifs) │
                   └────────────────┘
```

## Comment ça marche

### Détection des nouveaux runs

1. **Toutes les 15 minutes**, le scheduler vérifie chaque modèle
2. Pour **AROME/ARPEGE** : appel à l'API Météo-France (`GetCapabilities` WMS) qui retourne les runs disponibles
3. Pour **GFS** : vérification de l'existence du fichier sur NOMADS (requête HEAD)
4. Pour **ECMWF** : utilisation du package `ecmwf-opendata` (méthode `latest()`)
5. Si un nouveau run est détecté → notification aux utilisateurs abonnés

### Cache mémoire

Pour éviter de surcharger les APIs :
- Les derniers runs sont mis en cache pendant **5 minutes**
- La commande `/lastruns` utilise le cache
- Le scheduler rafraîchit le cache à chaque vérification

### Base de données

SQLite stocke :
- **Users** : chat_id, username, modèles suivis, runs suivis, statut actif
- **Last runs** : dernier run notifié par modèle (évite les doublons)

## Installation

### Prérequis

- Python 3.11+
- Compte Telegram
- Token bot Telegram (via [@BotFather](https://t.me/BotFather))
- Clés API Météo-France (gratuites sur [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr))

### Installation locale

```bash
# Cloner le repo
git clone <repo-url>
cd meteo-bot

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec tes tokens

# Lancer le bot
python bot.py
```

### Déploiement sur Railway

1. Créer un projet sur [Railway](https://railway.app)
2. Connecter le repo GitHub
3. Ajouter les variables d'environnement (voir ci-dessous)
4. Déployer

## Configuration

### Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token du bot Telegram |
| `AROME_API_KEY` | ✅ | Clé API Météo-France pour AROME |
| `ARPEGE_API_KEY` | ✅ | Clé API Météo-France pour ARPEGE |
| `DATABASE_PATH` | ❌ | Chemin SQLite (défaut: `bot.db`) |

### Obtenir les tokens

#### Token Telegram
1. Ouvrir [@BotFather](https://t.me/BotFather) sur Telegram
2. Envoyer `/newbot`
3. Suivre les instructions
4. Copier le token

#### Clés API Météo-France
1. Créer un compte sur [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr)
2. Aller dans "Mes API" → "AROME" → S'abonner
3. Générer un token (type "API Key")
4. Répéter pour ARPEGE

## Structure du projet

```
meteo-bot/
├── bot.py           # Handlers Telegram (commandes, boutons)
├── checker.py       # Détection des runs (APIs météo, cache)
├── scheduler.py     # Vérification périodique (toutes les 15 min)
├── database.py      # Accès SQLite (users, last_runs)
├── config.py        # Configuration (tokens, modèles)
├── requirements.txt # Dépendances Python
├── Procfile         # Config Railway
└── README.md        # Cette doc
```

## Dépendances

```
python-telegram-bot>=21.0   # Bot Telegram
requests>=2.31.0            # Requêtes HTTP
ecmwf-opendata>=0.3.0       # API ECMWF open data
```

## Contribution

Projet open source. PRs bienvenues !

## Auteur

**Quentin Jaud** — [Origami Aventures](https://origami-aventures.org)

## Licence

MIT
