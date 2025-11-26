"""
Configuration du bot météo - Wind Bot
"""
import os

# Telegram
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Base de données
DATABASE_PATH = os.environ.get("DATABASE_PATH", "bot.db")

# API Keys Météo-France
AROME_API_KEY = os.environ.get("AROME_API_KEY")
ARPEGE_API_KEY = os.environ.get("ARPEGE_API_KEY")

# ID admin pour tests (toi)
ADMIN_CHAT_ID = 673360042

# Modèles météo disponibles
MODELS = {
    "AROME": {
        "emoji": "⛵",
        "description": "Haute résolution France (1.3km)",
        "runs": [0, 3, 6, 12, 18],
    },
    "ARPEGE": {
        "emoji": "🌍",
        "description": "Europe/Monde (0.1°)",
        "runs": [0, 6, 12, 18],
    },
    "GFS": {
        "emoji": "🌎",
        "description": "Global NOAA (0.25°)",
        "runs": [0, 6, 12, 18],
    },
    "ECMWF": {
        "emoji": "🇪🇺",
        "description": "Centre Européen (0.25°)",
        "runs": [0, 6, 12, 18],
    },
}

# Runs disponibles pour abonnement
AVAILABLE_RUNS = [0, 6, 12, 18]

# Runs par défaut pour les nouveaux utilisateurs
# 06h → notif vers 11h-12h
# 12h → notif vers 16h-17h
# Pas de notification nocturne par défaut
DEFAULT_RUNS = [6, 12]
