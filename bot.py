"""
Bot Telegram - Notifications Modèles Météo
"""
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import BOT_TOKEN, MODELS, AVAILABLE_RUNS, ADMIN_CHAT_ID
from database import (
    init_database,
    get_or_create_user,
    get_user,
    get_user_models,
    get_user_runs,
    toggle_model_for_user,
    toggle_run_for_user,
    deactivate_user,
    reactivate_user,
    count_active_users,
)
from checker import get_all_latest_runs, get_all_cached_runs, init_cache

# Configuration logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============ COMMANDES ============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start - Inscription de l'utilisateur"""
    chat_id = update.message.chat.id
    username = update.message.from_user.username
    
    user = get_or_create_user(chat_id, username)
    
    # Si user existait et était inactif, le réactiver
    if not user["active"]:
        reactivate_user(chat_id)
    
    welcome_text = """
⛵ **Bienvenue sur Wind Updates Bot !**

Je te notifie en push quand de nouveaux runs de modèles météo sont disponibles.

📌 **Commandes :**
/models — Choisir les modèles à suivre
/runs — Choisir les runs (00h, 06h, 12h, 18h)
/status — Voir tes abonnements
/lastruns — Voir les derniers runs disponibles
/stop — Se désabonner

Commence par /models pour choisir tes modèles !
    """
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    logger.info(f"User {chat_id} ({username}) started the bot")


async def models_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /models - Choix des modèles à suivre"""
    chat_id = update.message.chat.id
    user_models = get_user_models(chat_id)
    
    keyboard = []
    
    for model_name, model_info in MODELS.items():
        emoji = model_info["emoji"]
        checked = "✅" if model_name in user_models else "⬜"
        button_text = f"{emoji} {model_name} {checked}"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_model_{model_name}"
            )
        ])
    
    # Bouton de confirmation
    keyboard.append([
        InlineKeyboardButton("✔️ Terminé", callback_data="done_models")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "**Choisis les modèles à suivre :**\n\n"
    for model_name, model_info in MODELS.items():
        text += f"{model_info['emoji']} **{model_name}** — {model_info['description']}\n"
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def runs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /runs - Choix des runs à suivre"""
    chat_id = update.message.chat.id
    user_runs = get_user_runs(chat_id)
    
    keyboard = []
    
    for run_hour in AVAILABLE_RUNS:
        checked = "✅" if run_hour in user_runs else "⬜"
        button_text = f"{run_hour:02d}h UTC {checked}"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_run_{run_hour}"
            )
        ])
    
    # Bouton tous/aucun
    keyboard.append([
        InlineKeyboardButton("🔄 Tous les runs", callback_data="all_runs"),
        InlineKeyboardButton("❌ Aucun", callback_data="no_runs"),
    ])
    
    # Bouton de confirmation
    keyboard.append([
        InlineKeyboardButton("✔️ Terminé", callback_data="done_runs")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "**Choisis les runs à suivre :**\n\n"
    text += "_(Liste vide = tous les runs)_\n\n"
    text += "• **00h** — Run de nuit\n"
    text += "• **06h** — Run du matin\n"
    text += "• **12h** — Run de midi\n"
    text += "• **18h** — Run du soir\n"
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /status - Affiche l'état des abonnements"""
    chat_id = update.message.chat.id
    user = get_user(chat_id)
    
    if not user:
        await update.message.reply_text(
            "Tu n'es pas encore inscrit. Utilise /start"
        )
        return
    
    if not user["active"]:
        await update.message.reply_text(
            "Tu es désabonné. Utilise /start pour te réabonner."
        )
        return
    
    models = user["models"]
    runs = user["runs"]
    
    status_text = "📊 **Tes abonnements :**\n\n"
    
    # Modèles
    status_text += "🔔 **Modèles suivis :**\n"
    if models:
        for model in models:
            emoji = MODELS.get(model, {}).get("emoji", "🌐")
            status_text += f"  • {emoji} {model}\n"
    else:
        status_text += "  _Aucun modèle sélectionné_\n"
    
    # Runs
    status_text += "\n⏰ **Runs suivis :**\n"
    if runs:
        runs_str = ", ".join([f"{r:02d}h" for r in sorted(runs)])
        status_text += f"  {runs_str} UTC\n"
    else:
        status_text += "  _Tous les runs_\n"
    
    # Conseil si config incomplète
    if not models:
        status_text += "\n⚠️ Configure tes modèles avec /models"
    
    await update.message.reply_text(status_text, parse_mode="Markdown")


async def lastruns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /lastruns - Affiche le dernier run de chaque modèle"""
    
    # Message d'attente
    wait_msg = await update.message.reply_text("🔍 Récupération des derniers runs...")
    
    # Récupérer les infos du cache
    cached_info = get_all_cached_runs()
    
    # Récupérer les derniers runs (avec cache)
    runs = get_all_latest_runs(force_refresh=False)
    
    now = datetime.now(timezone.utc)
    
    text = "📊 **Derniers runs disponibles :**\n\n"
    
    for model, run_dt in runs.items():
        emoji = MODELS.get(model, {}).get("emoji", "🌐")
        
        if run_dt:
            run_str = run_dt.strftime("%d/%m %Hh UTC")
            
            # Indiquer si c'est du cache
            cache_info = cached_info.get(model, {})
            if cache_info.get("is_fresh"):
                age = cache_info.get("age_seconds", 0)
                if age > 60:
                    cache_note = f" _(cache {age // 60}min)_"
                else:
                    cache_note = " _(cache)_"
            else:
                cache_note = " _(frais)_"
            
            text += f"{emoji} **{model}** : {run_str}{cache_note}\n"
        else:
            text += f"{emoji} **{model}** : _indisponible_\n"
    
    text += f"\n🕐 _Heure actuelle : {now.strftime('%H:%M')} UTC_"
    text += "\n\n💡 Le cache est rafraîchi toutes les 5 min."
    
    await wait_msg.edit_text(text, parse_mode="Markdown")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stop - Désabonnement"""
    chat_id = update.message.chat.id
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Oui, me désabonner", callback_data="confirm_stop"),
            InlineKeyboardButton("❌ Annuler", callback_data="cancel_stop"),
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Es-tu sûr de vouloir te désabonner ?\n\n"
        "Tu ne recevras plus de notifications.",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help - Aide"""
    help_text = """
⛵ **Wind Updates Bot — Aide**

**Commandes disponibles :**
/start — S'inscrire ou se réabonner
/models — Choisir les modèles météo
/runs — Choisir les heures de run
/status — Voir ses abonnements
/lastruns — Voir les derniers runs disponibles
/stop — Se désabonner
/help — Afficher cette aide

**Modèles disponibles :**
• **AROME** — Haute résolution France
• **ARPEGE** — Europe/Monde
• **GFS** — Global NOAA
• **ECMWF** — Centre Européen

**Comment ça marche ?**
1. Choisis tes modèles avec /models
2. Optionnel : filtre les runs avec /runs
3. Reçois une notification push dès qu'un run est dispo !

📬 Contact : @quentin\\_jaud
    """
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ============ CALLBACKS (BOUTONS) ============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère tous les clics sur les boutons inline"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data
    
    # ----- TOGGLE MODÈLE -----
    if data.startswith("toggle_model_"):
        model = data.replace("toggle_model_", "")
        enabled = toggle_model_for_user(chat_id, model)
        
        # Reconstruire le clavier avec le nouvel état
        user_models = get_user_models(chat_id)
        keyboard = []
        
        for model_name, model_info in MODELS.items():
            emoji = model_info["emoji"]
            checked = "✅" if model_name in user_models else "⬜"
            button_text = f"{emoji} {model_name} {checked}"
            
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"toggle_model_{model_name}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("✔️ Terminé", callback_data="done_models")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "**Choisis les modèles à suivre :**\n\n"
        for model_name, model_info in MODELS.items():
            text += f"{model_info['emoji']} **{model_name}** — {model_info['description']}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- TOGGLE RUN -----
    elif data.startswith("toggle_run_"):
        run_hour = int(data.replace("toggle_run_", ""))
        enabled = toggle_run_for_user(chat_id, run_hour)
        
        # Reconstruire le clavier
        user_runs = get_user_runs(chat_id)
        keyboard = build_runs_keyboard(user_runs)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "**Choisis les runs à suivre :**\n\n_(Liste vide = tous les runs)_"
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- TOUS LES RUNS -----
    elif data == "all_runs":
        from database import update_user_runs
        update_user_runs(chat_id, [])  # Liste vide = tous
        
        keyboard = build_runs_keyboard([])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "**Choisis les runs à suivre :**\n\n_(Liste vide = tous les runs)_"
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- AUCUN RUN -----
    elif data == "no_runs":
        from database import update_user_runs
        update_user_runs(chat_id, AVAILABLE_RUNS.copy())
        
        keyboard = build_runs_keyboard(AVAILABLE_RUNS.copy())
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "**Choisis les runs à suivre :**\n\n_(Décoche ceux que tu ne veux pas)_"
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- TERMINÉ MODÈLES -----
    elif data == "done_models":
        models = get_user_models(chat_id)
        if models:
            models_str = ", ".join(models)
            await query.edit_message_text(
                f"✅ **Modèles enregistrés :**\n{models_str}\n\n"
                f"Utilise /runs pour filtrer les runs, ou /status pour voir tes abonnements.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "⚠️ Tu n'as sélectionné aucun modèle.\n\n"
                "Utilise /models pour en choisir.",
                parse_mode="Markdown"
            )
    
    # ----- TERMINÉ RUNS -----
    elif data == "done_runs":
        runs = get_user_runs(chat_id)
        if runs:
            runs_str = ", ".join([f"{r:02d}h" for r in sorted(runs)])
            await query.edit_message_text(
                f"✅ **Runs enregistrés :**\n{runs_str} UTC\n\n"
                f"Utilise /status pour voir tes abonnements.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "✅ **Tous les runs activés**\n\n"
                "Tu seras notifié pour chaque run de tes modèles.\n"
                "Utilise /status pour voir tes abonnements.",
                parse_mode="Markdown"
            )
    
    # ----- CONFIRMER STOP -----
    elif data == "confirm_stop":
        deactivate_user(chat_id)
        await query.edit_message_text(
            "👋 Tu as été désabonné.\n\n"
            "Utilise /start pour te réabonner."
        )
        logger.info(f"User {chat_id} unsubscribed")
    
    # ----- ANNULER STOP -----
    elif data == "cancel_stop":
        await query.edit_message_text("Désabonnement annulé. ✌️")


def build_runs_keyboard(user_runs: list) -> list:
    """Construit le clavier pour les runs"""
    keyboard = []
    
    for run_hour in AVAILABLE_RUNS:
        checked = "✅" if run_hour in user_runs else "⬜"
        button_text = f"{run_hour:02d}h UTC {checked}"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_run_{run_hour}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔄 Tous les runs", callback_data="all_runs"),
        InlineKeyboardButton("❌ Aucun", callback_data="no_runs"),
    ])
    
    keyboard.append([
        InlineKeyboardButton("✔️ Terminé", callback_data="done_runs")
    ])
    
    return keyboard


# ============ ADMIN ============

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /stats - Stats admin (toi uniquement)"""
    chat_id = update.message.chat.id
    
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Commande réservée à l'admin.")
        return
    
    total_users = count_active_users()
    
    stats_text = f"""
📈 **Stats Admin**

👥 Utilisateurs actifs : {total_users}
    """
    
    await update.message.reply_text(stats_text, parse_mode="Markdown")


# ============ MAIN ============

def main():
    """Point d'entrée principal"""
    
    # Vérifier le token
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN non défini")
        return
    
    # Initialiser la base de données
    init_database()
    
    # Pré-charger le cache des runs
    init_cache()
    
    # Créer l'application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Ajouter les handlers de commandes
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CommandHandler("runs", runs_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("lastruns", lastruns_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", admin_stats_command))
    
    # Handler pour les boutons
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Intégrer le scheduler de vérification des runs
    from scheduler import start_scheduler
    start_scheduler(app)
    
    # Lancer le bot
    print("🚀 Bot démarré")
    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
