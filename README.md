# Wind Updates Bot 🌊

Bot Telegram qui notifie en push quand de nouveaux runs de modèles météorologiques sont disponibles.

## Modèles supportés

- **AROME** — Haute résolution France (1.3km)
- **ARPEGE** — Europe/Monde (0.1°)
- **GFS** — Global NOAA (0.25°)
- **ECMWF** — Centre Européen (0.25°)

## Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/start` | S'inscrire au bot |
| `/models` | Choisir les modèles à suivre |
| `/runs` | Choisir les runs (00h, 06h, 12h, 18h) |
| `/status` | Voir ses abonnements |
| `/stop` | Se désabonner |
| `/help` | Aide |

## Installation locale

```bash
# Cloner le repo
git clone <repo-url>
cd meteo-bot

# Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec ton token Telegram

# Lancer le bot
python bot.py
```

## Déploiement sur Railway

1. Connecter ton repo GitHub à Railway
2. Ajouter la variable d'environnement `TELEGRAM_BOT_TOKEN`
3. Railway détecte automatiquement le `Procfile` et déploie

## Structure du projet

```
meteo-bot/
├── bot.py              # Bot Telegram (handlers, commandes)
├── config.py           # Configuration et constantes
├── database.py         # Gestion SQLite
├── requirements.txt    # Dépendances Python
├── Procfile            # Configuration Railway
├── .env.example        # Template variables d'environnement
└── README.md           # Cette doc
```

## Variables d'environnement

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token du bot (@BotFather) | ✅ |
| `DATABASE_PATH` | Chemin SQLite (défaut: bot.db) | ❌ |

## Auteur

Quentin Jaud — [Origami Aventures](https://origami-aventures.org)
