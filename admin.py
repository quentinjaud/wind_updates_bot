"""
Wind Bot - Module Admin
Fonctions administrateur et notifications d'erreurs
V1.2.1
"""
import logging
from datetime import datetime, timezone

from config import ADMIN_CHAT_ID
from database import count_active_users, get_connection

logger = logging.getLogger(__name__)


# ============ SYSTÈME DE NOTIFICATIONS ADMIN ============

# Throttling des notifications d'erreurs : {error_type: last_sent_timestamp}
_admin_notif_throttle = {}
ADMIN_THROTTLE_MINUTES = 10


async def send_admin_notification(bot, message: str, error_type: str = "general"):
    """
    Envoie une notification à l'admin avec throttling.
    
    Args:
        bot: Instance du bot Telegram
        message: Message à envoyer
        error_type: Type d'erreur pour le throttling (ex: "db_error", "api_timeout")
    
    Returns:
        True si notif envoyée, False sinon
    """
    if not ADMIN_CHAT_ID or ADMIN_CHAT_ID == 0:
        logger.warning("⚠️ ADMIN_CHAT_ID non configuré, notification ignorée")
        return False
    
    # Vérifier throttling
    now = datetime.now(timezone.utc)
    last_sent = _admin_notif_throttle.get(error_type)
    
    if last_sent:
        elapsed = (now - last_sent).total_seconds() / 60
        if elapsed < ADMIN_THROTTLE_MINUTES:
            logger.debug(f"Admin notif throttled: {error_type} (envoyée il y a {elapsed:.1f}min)")
            return False
    
    # Envoyer notification
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 **Admin Alert**\n\n{message}",
            parse_mode="Markdown"
        )
        _admin_notif_throttle[error_type] = now
        logger.info(f"✅ Admin notifié: {error_type}")
        return True
    except Exception as e:
        logger.error(f"❌ Échec notification admin: {e}")
        return False


def count_logs_for_stats():
    """Compte le nombre total de logs disponibles"""
    try:
        conn = get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM run_availability_log")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0


# ============ COMMANDES ADMIN ============

async def admin_stats_command(update, context):
    """Commande /stats - Stats admin"""
    chat_id = update.message.chat.id
    
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Commande réservée à l'admin.")
        return
    
    total_users = count_active_users()
    logs_count = count_logs_for_stats()
    
    stats_text = f"""
📈 **Stats Admin**

👥 Utilisateurs actifs : {total_users}
📊 Logs disponibilité : {logs_count}
    """
    
    await update.message.reply_text(stats_text, parse_mode="Markdown")


async def testnotif_command(update, context):
    """Commande /testnotif - Envoie une notification de test (admin only)"""
    chat_id = update.message.chat.id
    
    if chat_id != ADMIN_CHAT_ID:
        return
    
    from scheduler import send_notification
    
    # Simuler une notification pour le run 12h d'aujourd'hui
    fake_run = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    
    await update.message.reply_text("📤 Envoi d'une notification de test...")
    await send_notification(context.bot, chat_id, "AROME", fake_run)
    await update.message.reply_text("✅ Notification de test envoyée")


async def forcecheck_command(update, context):
    """Commande /forcecheck - Force une vérification immédiate (admin only)"""
    chat_id = update.message.chat.id
    
    if chat_id != ADMIN_CHAT_ID:
        return
    
    await update.message.reply_text("🔍 Vérification des modèles en cours...")
    
    from scheduler import check_all_models
    await check_all_models(context.bot)
    
    await update.message.reply_text("✅ Vérification terminée. Regarde les logs pour les détails.")
