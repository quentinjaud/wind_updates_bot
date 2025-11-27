"""
Gestion de la base de données SQLite
"""
import sqlite3
import json
import os
import logging
from datetime import datetime, timezone

# Configuration du chemin de la base de données
# Par défaut : répertoire courant
# Avec volume Railway : /data/wind_bot.db
DATABASE_PATH = os.getenv("DB_PATH", "wind_bot.db")

logger = logging.getLogger(__name__)


def get_connection():
    """Retourne une connexion à la base de données"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def check_persistence():
    """Vérifie et log l'état de la persistence de la base de données"""
    db_abs_path = os.path.abspath(DATABASE_PATH)
    db_exists = os.path.exists(DATABASE_PATH)
    
    logger.info(f"📁 Database path: {db_abs_path}")
    logger.info(f"📁 Database exists: {db_exists}")
    
    if db_exists:
        db_size = os.path.getsize(DATABASE_PATH)
        logger.info(f"📁 Database size: {db_size} bytes")
        
        # Compter les données existantes
        conn = get_connection()
        try:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            runs_count = conn.execute("SELECT COUNT(*) FROM last_runs").fetchone()[0]
            logger.info(f"🔍 PERSISTENCE CHECK - Users: {user_count}, Last runs: {runs_count}")
            
            if user_count == 0 and runs_count == 0:
                logger.warning("⚠️  Database is empty - might not be persisted between deploys!")
            else:
                logger.info("✅ Database contains data - persistence seems OK")
        except sqlite3.OperationalError:
            logger.warning("⚠️  Tables don't exist yet - first run")
        finally:
            conn.close()
    else:
        logger.info("📝 Database doesn't exist yet - will be created")


def init_database():
    """Initialise les tables si elles n'existent pas"""
    # Vérifier la persistence avant d'initialiser
    check_persistence()
    
    conn = get_connection()
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            models TEXT DEFAULT '[]',
            runs TEXT DEFAULT '[]',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_notification TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS last_runs (
            model TEXT PRIMARY KEY,
            run_datetime TEXT NOT NULL,
            notified_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)")
    
    conn.commit()
    conn.close()
    
    logger.info("✅ Database initialized")
    
    # Re-check après init pour voir le résultat
    check_persistence()


# ============ USERS ============

def get_user(chat_id: int) -> dict | None:
    """Récupère un utilisateur par son chat_id"""
    conn = get_connection()
    cursor = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "chat_id": row["chat_id"],
            "username": row["username"],
            "models": json.loads(row["models"]),
            "runs": json.loads(row["runs"]),
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "last_notification": row["last_notification"],
        }
    return None


def create_user(chat_id: int, username: str = None) -> dict:
    """Crée un nouvel utilisateur"""
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO users (chat_id, username) VALUES (?, ?)",
        (chat_id, username)
    )
    conn.commit()
    conn.close()
    return get_user(chat_id)


def get_or_create_user(chat_id: int, username: str = None) -> dict:
    """Récupère ou crée un utilisateur"""
    user = get_user(chat_id)
    if user:
        return user
    return create_user(chat_id, username)


def update_user_models(chat_id: int, models: list):
    """Met à jour les modèles d'un utilisateur"""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET models = ? WHERE chat_id = ?",
        (json.dumps(models), chat_id)
    )
    conn.commit()
    conn.close()


def update_user_runs(chat_id: int, runs: list):
    """Met à jour les runs d'un utilisateur"""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET runs = ? WHERE chat_id = ?",
        (json.dumps(runs), chat_id)
    )
    conn.commit()
    conn.close()


def get_user_models(chat_id: int) -> list:
    """Récupère les modèles d'un utilisateur"""
    user = get_user(chat_id)
    return user["models"] if user else []


def get_user_runs(chat_id: int) -> list:
    """Récupère les runs d'un utilisateur"""
    user = get_user(chat_id)
    return user["runs"] if user else []


def toggle_model_for_user(chat_id: int, model: str) -> bool:
    """Active/désactive un modèle pour un utilisateur. Retourne le nouvel état."""
    # S'assurer que l'utilisateur existe
    get_or_create_user(chat_id)
    
    models = get_user_models(chat_id)
    
    if model in models:
        models.remove(model)
        enabled = False
    else:
        models.append(model)
        enabled = True
    
    update_user_models(chat_id, models)
    return enabled


def toggle_run_for_user(chat_id: int, run_hour: int) -> bool:
    """Active/désactive un run pour un utilisateur. Retourne le nouvel état."""
    # S'assurer que l'utilisateur existe
    get_or_create_user(chat_id)
    
    runs = get_user_runs(chat_id)
    
    if run_hour in runs:
        runs.remove(run_hour)
        enabled = False
    else:
        runs.append(run_hour)
        enabled = True
    
    update_user_runs(chat_id, runs)
    return enabled


def deactivate_user(chat_id: int):
    """Désactive un utilisateur"""
    conn = get_connection()
    conn.execute("UPDATE users SET active = 0 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def reactivate_user(chat_id: int):
    """Réactive un utilisateur"""
    conn = get_connection()
    conn.execute("UPDATE users SET active = 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def get_active_users() -> list:
    """Récupère tous les utilisateurs actifs"""
    conn = get_connection()
    cursor = conn.execute("SELECT * FROM users WHERE active = 1")
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "chat_id": row["chat_id"],
            "username": row["username"],
            "models": json.loads(row["models"]),
            "runs": json.loads(row["runs"]),
        }
        for row in rows
    ]


def get_subscribed_users(model: str, run_hour: int) -> list[int]:
    """Récupère les chat_ids des utilisateurs abonnés à un modèle/run"""
    users = get_active_users()
    subscribed = []
    
    for user in users:
        # Vérifie abonnement au modèle
        if model not in user["models"]:
            continue
        
        # Vérifie abonnement au run (liste vide = tous les runs)
        if user["runs"] and run_hour not in user["runs"]:
            continue
        
        subscribed.append(user["chat_id"])
    
    return subscribed


def count_active_users() -> int:
    """Compte le nombre d'utilisateurs actifs"""
    conn = get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM users WHERE active = 1")
    count = cursor.fetchone()[0]
    conn.close()
    return count


# ============ LAST RUNS ============

def save_last_run(model: str, run_datetime: datetime):
    """Sauvegarde le dernier run notifié pour un modèle"""
    # Convertir en ISO string pour stockage SQLite
    if run_datetime.tzinfo is None:
        run_datetime = run_datetime.replace(tzinfo=timezone.utc)
    
    iso_string = run_datetime.isoformat()
    
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO last_runs (model, run_datetime, notified_at) VALUES (?, ?, ?)",
        (model, iso_string, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def get_last_run(model: str) -> datetime | None:
    """Récupère le dernier run notifié pour un modèle"""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT run_datetime FROM last_runs WHERE model = ?",
        (model,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row and row["run_datetime"]:
        # Parser la string ISO en datetime
        try:
            dt = datetime.fromisoformat(row["run_datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    
    return None


def is_new_run(model: str, run_datetime: datetime) -> bool:
    """Vérifie si c'est un nouveau run (pas encore notifié)"""
    last = get_last_run(model)
    
    if last is None:
        return True
    
    # S'assurer que les deux sont timezone-aware pour comparaison
    if run_datetime.tzinfo is None:
        run_datetime = run_datetime.replace(tzinfo=timezone.utc)
    
    return run_datetime > last
