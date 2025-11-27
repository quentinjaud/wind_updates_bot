"""
Scheduler pour la vérification périodique des runs météo
Wind Bot - V1.1 avec logging des disponibilités
V1.2 avec notifications admin pour erreurs critiques
"""
import logging
import asyncio
from datetime import datetime, timezone

from config import MODELS
from database import (
    get_last_run,
    save_last_run,
    is_new_run,
    get_subscribed_users,
    log_run_availability,  # V1.1
    cleanup_old_logs,       # V1.1
)
from checker import check_model_availability, get_expected_run

logger = logging.getLogger(__name__)

# Intervalle entre les vérifications (en secondes)
CHECK_INTERVAL = 15 * 60  # 15 minutes


def should_cleanup():
    """
    Détermine si on doit faire le cleanup des logs.
    Retourne True une fois par an (1er janvier à 3h du matin UTC).
    """
    now = datetime.now(timezone.utc)
    return now.month == 1 and now.day == 1 and now.hour == 3 and now.minute < 15


async def send_notification(bot, chat_id: int, model: str, run_datetime: datetime):
    """
    Envoie une notification à un utilisateur.
    """
    emoji_map = {
        "AROME": "⛵",
        "ARPEGE": "🌍",
        "GFS": "🌎",
        "ECMWF": "🇪🇺",
    }
    
    emoji = emoji_map.get(model, "🌐")
    run_hour = run_datetime.hour
    run_date = run_datetime.strftime("%d/%m/%Y")
    now = datetime.now(timezone.utc)
    
    message = f"""
{emoji} **Nouveau run disponible !**

📊 **Modèle :** {model}
⏰ **Run :** {run_hour:02d}h UTC
📅 **Date :** {run_date}
🕐 **Notifié à :** {now.strftime("%H:%M")} UTC

🔗 **Liens :**
• [Meteociel](https://www.meteociel.fr/modeles/)
• [Windy](https://www.windy.com/)
"""
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        logger.info(f"Notification envoyée à {chat_id}: {model} {run_hour}h")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi notification à {chat_id}: {e}")
        
        # V1.2: Notifier admin en cas d'échec critique
        from bot import send_admin_notification
        try:
            await send_admin_notification(
                bot,
                f"❌ **Échec notification utilisateur**\n\n"
                f"User: `{chat_id}`\n"
                f"Modèle: {model} {run_hour:02d}h\n"
                f"Erreur: `{str(e)[:100]}`",
                error_type="notification_failure"
            )
        except:
            pass  # Éviter boucle infinie si admin notif échoue aussi
        
        return False


async def check_and_notify(bot, model: str):
    """
    Vérifie un modèle et notifie les utilisateurs si nouveau run.
    """
    current_time = datetime.now(timezone.utc)
    
    # Calculer le run attendu
    try:
        expected_run = get_expected_run(model, current_time)
    except Exception as e:
        logger.error(f"{model}: Erreur get_expected_run: {e}")
        
        # V1.2: Notifier admin pour erreur API critique
        from bot import send_admin_notification
        await send_admin_notification(
            bot,
            f"❌ **Erreur API météo**\n\n"
            f"Modèle: {model}\n"
            f"Erreur: `{str(e)[:150]}`",
            error_type=f"api_error_{model.lower()}"
        )
        return
    
    if not expected_run:
        logger.debug(f"{model}: pas de run attendu")
        return
    
    # Vérifier si c'est un nouveau run (pas encore notifié)
    try:
        if not is_new_run(model, expected_run):
            logger.debug(f"{model}: run {expected_run} déjà notifié")
            return
    except Exception as e:
        logger.error(f"{model}: Erreur DB is_new_run: {e}")
        
        # V1.2: Notifier admin pour erreur DB critique
        from bot import send_admin_notification
        await send_admin_notification(
            bot,
            f"❌ **Erreur base de données**\n\n"
            f"Fonction: `is_new_run`\n"
            f"Modèle: {model}\n"
            f"Erreur: `{str(e)[:150]}`",
            error_type="db_error"
        )
        return
    
    # Vérifier la disponibilité réelle
    logger.info(f"{model}: vérification disponibilité run {expected_run}")
    
    try:
        is_available = check_model_availability(model, expected_run)
    except Exception as e:
        logger.error(f"{model}: Erreur check_model_availability: {e}")
        
        # V1.2: Notifier admin pour timeout/erreur API
        from bot import send_admin_notification
        await send_admin_notification(
            bot,
            f"❌ **Timeout API météo**\n\n"
            f"Modèle: {model}\n"
            f"Run: {expected_run.strftime('%Y-%m-%d %H:00 UTC')}\n"
            f"Erreur: `{str(e)[:150]}`",
            error_type=f"api_timeout_{model.lower()}"
        )
        return
    
    if not is_available:
        logger.debug(f"{model}: run {expected_run} pas encore disponible")
        return
    
    # Nouveau run disponible !
    detected_at = datetime.now(timezone.utc)  # V1.1: timestamp de détection
    
    logger.info(f"✅ {model}: nouveau run {expected_run} détecté !")
    
    # Récupérer les utilisateurs abonnés
    run_hour = expected_run.hour
    
    try:
        subscribed_users = get_subscribed_users(model, run_hour)
    except Exception as e:
        logger.error(f"{model}: Erreur DB get_subscribed_users: {e}")
        
        # V1.2: Notifier admin pour erreur DB
        from bot import send_admin_notification
        await send_admin_notification(
            bot,
            f"❌ **Erreur base de données**\n\n"
            f"Fonction: `get_subscribed_users`\n"
            f"Modèle: {model}\n"
            f"Erreur: `{str(e)[:150]}`",
            error_type="db_error"
        )
        return
    
    logger.info(f"{model}: {len(subscribed_users)} utilisateurs à notifier")
    
    # Envoyer les notifications
    success_count = 0
    for chat_id in subscribed_users:
        success = await send_notification(bot, chat_id, model, expected_run)
        if success:
            success_count += 1
        
        # Rate limiting Telegram (30 msg/sec max)
        await asyncio.sleep(0.05)
    
    logger.info(f"{model}: {success_count}/{len(subscribed_users)} notifications envoyées")
    
    # V1.1: Logger la disponibilité du run
    try:
        log_run_availability(model, expected_run, detected_at)
    except Exception as e:
        logger.error(f"{model}: Erreur log_run_availability: {e}")
        # Pas critique, on ne notifie pas l'admin pour ça
    
    # Marquer le run comme notifié
    try:
        save_last_run(model, expected_run)
    except Exception as e:
        logger.error(f"{model}: Erreur save_last_run: {e}")
        
        # V1.2: Notifier admin car critique (risque de double notif)
        from bot import send_admin_notification
        await send_admin_notification(
            bot,
            f"❌ **Erreur base de données**\n\n"
            f"Fonction: `save_last_run`\n"
            f"Modèle: {model}\n"
            f"⚠️ Risque de double notification !\n"
            f"Erreur: `{str(e)[:150]}`",
            error_type="db_error"
        )


async def check_all_models(bot):
    """
    Vérifie tous les modèles.
    """
    logger.info("🔍 Début vérification des modèles...")
    
    for model in MODELS.keys():
        try:
            await check_and_notify(bot, model)
        except Exception as e:
            logger.error(f"Erreur inattendue vérification {model}: {e}")
            
            # V1.2: Notifier admin pour exception inattendue
            from bot import send_admin_notification
            await send_admin_notification(
                bot,
                f"❌ **Exception inattendue**\n\n"
                f"Modèle: {model}\n"
                f"Erreur: `{str(e)[:200]}`",
                error_type=f"unexpected_{model.lower()}"
            )
        
        # Petite pause entre les modèles
        await asyncio.sleep(1)
    
    # V1.1: Cleanup annuel des logs
    if should_cleanup():
        try:
            deleted = cleanup_old_logs(days=365)
            logger.info(f"🧹 Cleanup annuel effectué : {deleted} logs supprimés")
        except Exception as e:
            logger.error(f"Erreur cleanup logs: {e}")
            # Pas critique, on ne notifie pas l'admin
    
    logger.info("✅ Fin vérification des modèles")


async def scheduler_loop(bot):
    """
    Boucle principale du scheduler.
    """
    logger.info(f"🚀 Scheduler démarré (intervalle: {CHECK_INTERVAL}s)")
    
    while True:
        try:
            await check_all_models(bot)
        except Exception as e:
            logger.error(f"Erreur critique scheduler: {e}")
            
            # V1.2: Notifier admin pour erreur critique scheduler
            from bot import send_admin_notification
            try:
                await send_admin_notification(
                    bot,
                    f"🚨 **ERREUR CRITIQUE SCHEDULER**\n\n"
                    f"Le scheduler a rencontré une erreur majeure.\n"
                    f"Erreur: `{str(e)[:200]}`",
                    error_type="scheduler_critical"
                )
            except:
                pass  # Dernier recours
        
        # Attendre avant la prochaine vérification
        await asyncio.sleep(CHECK_INTERVAL)


def start_scheduler(app):
    """
    Démarre le scheduler dans le contexte de l'application Telegram.
    """
    async def post_init(application):
        """Callback appelé après l'initialisation du bot."""
        # Créer la tâche du scheduler
        asyncio.create_task(scheduler_loop(application.bot))
        logger.info("Scheduler initialisé")
    
    app.post_init = post_init
