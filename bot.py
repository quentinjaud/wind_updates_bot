"""
Wind Bot - Notifications Modèles Météo
Bot Telegram qui prévient quand les runs météo sont disponibles
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

from config import BOT_TOKEN, MODELS, AVAILABLE_RUNS, ADMIN_CHAT_ID, DEFAULT_RUNS
from database import (
    init_database,
    get_or_create_user,
    get_user,
    get_user_models,
    get_user_runs,
    toggle_model_for_user,
    toggle_run_for_user,
    update_user_runs,
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

# Réduire la verbosité de httpx (utilisé par telegram bot)
logging.getLogger("httpx").setLevel(logging.WARNING)


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
🌊 **Bienvenue sur Wind Bot !**

Je te préviens dès qu'un nouveau run météo est disponible.

✅ Tu es abonné par défaut aux runs **06h** et **12h**.
→ Notifications vers midi et 17h, pas de réveil nocturne 😴

Pour ajouter d'autres runs (00h, 18h) → /horaires

🆕 Nouveau ici ? Tape /aide pour comprendre les runs.

📋 **Commandes :**
/modeles — Choisir les modèles (AROME, GFS...)
/horaires — Choisir quels runs recevoir
/statut — Voir tes abonnements
/derniers — Derniers runs disponibles
/aide — Comprendre les runs météo
    """
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    logger.info(f"User {chat_id} ({username}) started the bot")


async def aide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /aide - Explique le fonctionnement des modèles météo"""
    
    aide_text = """
📚 **Comment ça marche ?**

Les modèles météo (AROME, GFS...) calculent des prévisions plusieurs fois par jour. Chaque calcul s'appelle un **run**.

🕐 **Pourquoi un délai ?**
Un run "00h" utilise les observations de 00h UTC, mais le calcul prend du temps. Il sort donc quelques heures plus tard.

⏰ **Horaires de disponibilité (heure de Paris) :**

**AROME** ⛵ (France, très précis) :
• Run 00h → dispo vers 03h45
• Run 06h → dispo vers 12h10
• Run 12h → dispo vers 16h55
• Run 18h → dispo vers 00h10

**ARPEGE** 🌍 (Europe/Monde) :
• Run 00h → dispo vers 04h50
• Run 06h → dispo vers 11h35
• Run 12h → dispo vers 16h25
• Run 18h → dispo vers 23h35

**GFS** 🌎 (Monde, américain) :
• Runs 00h/06h/12h/18h → dispo 4-5h après

**ECMWF** 🇪🇺 (Monde, référence) :
• Runs 00h/06h/12h/18h → dispo 8-10h après

💡 **Conseil nav :**
Pour une nav le matin, consulte le run 00h dès qu'il sort (~04h).
Pour une nav l'après-midi, attends le run 06h (~12h).

📋 **Commandes :**
/modeles — Choisir les modèles
/horaires — Choisir quels runs recevoir
/statut — Voir tes abonnements
/derniers — Derniers runs disponibles
/arreter — Se désabonner
    """
    
    await update.message.reply_text(aide_text, parse_mode="Markdown")


async def modeles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /modeles - Choix des modèles à suivre"""
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


async def horaires_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /horaires - Choix des runs à suivre"""
    chat_id = update.message.chat.id
    user_runs = get_user_runs(chat_id)
    
    keyboard = build_horaires_keyboard(user_runs)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = """**Choisis les runs à suivre :**

🌙 = notification de nuit (peut réveiller)
☀️ = notification de jour

_(Par défaut : 06h et 12h uniquement)_"""
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def statut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /statut - Affiche l'état des abonnements"""
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
        status_text += "\n⚠️ Configure tes modèles avec /modeles"
    
    await update.message.reply_text(status_text, parse_mode="Markdown")


async def derniers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /derniers - Affiche le dernier run de chaque modèle"""
    
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


async def arreter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /arreter - Désabonnement"""
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
        toggle_model_for_user(chat_id, model)
        
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
        toggle_run_for_user(chat_id, run_hour)
        
        # Reconstruire le clavier
        user_runs = get_user_runs(chat_id)
        keyboard = build_horaires_keyboard(user_runs)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """**Choisis les runs à suivre :**

🌙 = notification de nuit (peut réveiller)
☀️ = notification de jour

_(Par défaut : 06h et 12h uniquement)_"""
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- TOUS LES RUNS -----
    elif data == "all_runs":
        update_user_runs(chat_id, AVAILABLE_RUNS.copy())
        
        keyboard = build_horaires_keyboard(AVAILABLE_RUNS.copy())
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """**Choisis les runs à suivre :**

🌙 = notification de nuit (peut réveiller)
☀️ = notification de jour

⚠️ _Attention : tu recevras des notifications la nuit !_"""
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- RUNS PAR DÉFAUT (JOUR) -----
    elif data == "default_runs":
        update_user_runs(chat_id, DEFAULT_RUNS.copy())
        
        keyboard = build_horaires_keyboard(DEFAULT_RUNS.copy())
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """**Choisis les runs à suivre :**

🌙 = notification de nuit (peut réveiller)
☀️ = notification de jour

✅ _Runs de jour uniquement (06h, 12h)_"""
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ----- TERMINÉ MODÈLES -----
    elif data == "done_models":
        models = get_user_models(chat_id)
        if models:
            models_str = ", ".join(models)
            await query.edit_message_text(
                f"✅ **Modèles enregistrés :**\n{models_str}\n\n"
                f"Utilise /horaires pour choisir les runs, ou /statut pour voir tes abonnements.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "⚠️ Tu n'as sélectionné aucun modèle.\n\n"
                "Utilise /modeles pour en choisir.",
                parse_mode="Markdown"
            )
    
    # ----- TERMINÉ HORAIRES -----
    elif data == "done_runs":
        runs = get_user_runs(chat_id)
        if runs:
            runs_str = ", ".join([f"{r:02d}h" for r in sorted(runs)])
            night_warning = ""
            if 0 in runs or 18 in runs:
                night_warning = "\n\n🌙 _Tu recevras des notifications la nuit._"
            await query.edit_message_text(
                f"✅ **Runs enregistrés :**\n{runs_str} UTC{night_warning}\n\n"
                f"Utilise /statut pour voir tes abonnements.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "✅ **Tous les runs activés**\n\n"
                "Tu seras notifié pour chaque run de tes modèles.\n"
                "🌙 _Attention : notifications de nuit incluses !_\n\n"
                "Utilise /statut pour voir tes abonnements.",
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


def build_horaires_keyboard(user_runs: list) -> list:
    """Construit le clavier pour les horaires de runs"""
    keyboard = []
    
    # Infos sur chaque run
    run_info = [
        (0, "🌙", "nuit ~04h"),
        (6, "☀️", "jour ~12h"),
        (12, "☀️", "jour ~17h"),
        (18, "🌙", "nuit ~00h"),
    ]
    
    for run_hour, emoji, timing in run_info:
        checked = "✅" if run_hour in user_runs else "⬜"
        button_text = f"{emoji} Run {run_hour:02d}h → {timing} {checked}"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_run_{run_hour}"
            )
        ])
    
    # Boutons raccourcis
    keyboard.append([
        InlineKeyboardButton("☀️ Jour seul", callback_data="default_runs"),
        InlineKeyboardButton("🔔 Tous", callback_data="all_runs"),
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


async def testnotif_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def forcecheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /forcecheck - Force une vérification immédiate (admin only)"""
    chat_id = update.message.chat.id
    
    if chat_id != ADMIN_CHAT_ID:
        return
    
    await update.message.reply_text("🔍 Vérification des modèles en cours...")
    
    from scheduler import check_all_models
    await check_all_models(context.bot)
    
    await update.message.reply_text("✅ Vérification terminée. Regarde les logs pour les détails.")


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
    
    # Ajouter les handlers de commandes (en français)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("aide", aide_command))
    app.add_handler(CommandHandler("modeles", modeles_command))
    app.add_handler(CommandHandler("horaires", horaires_command))
    app.add_handler(CommandHandler("statut", statut_command))
    app.add_handler(CommandHandler("derniers", derniers_command))
    app.add_handler(CommandHandler("arreter", arreter_command))
    
    # Commandes admin
    app.add_handler(CommandHandler("stats", admin_stats_command))
    app.add_handler(CommandHandler("testnotif", testnotif_command))
    app.add_handler(CommandHandler("forcecheck", forcecheck_command))
    
    # Handler pour les boutons
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Intégrer le scheduler de vérification des runs
    from scheduler import start_scheduler
    start_scheduler(app)
    
    # Lancer le bot
    print("🚀 Wind Bot démarré")
    logger.info("Wind Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
