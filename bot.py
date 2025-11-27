"""
Wind Bot - Notifications Modèles Météo
Bot Telegram qui prévient quand les runs météo sont disponibles
V1.1 avec commande /prochain (prédiction ETAs)
V1.1.2 avec commande /lol (blagues)
V1.2 avec notifications admin (erreurs critiques + nouveaux users)
V1.2.1 fix CallbackQuery.bot → context.bot
V1.2.2 admin.py séparé + notification async
"""
import logging
import requests
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import BOT_TOKEN, MODELS, AVAILABLE_RUNS, DEFAULT_RUNS
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
    get_next_run_eta,  # V1.1
    get_average_delay, # V1.1
    get_log_stats,     # V1.1
)
from checker import get_all_latest_runs, get_all_cached_runs, init_cache
from admin import (
    send_admin_notification,
    admin_stats_command,
    testnotif_command,
    forcecheck_command,
    count_logs_for_stats,
)

import sys

# Configuration logging - TOUT sur stdout pour Railway
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout  # Force stdout au lieu de stderr
)
logger = logging.getLogger(__name__)

# Réduire la verbosité de httpx (utilisé par telegram bot)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ============ CONSTANTES POUR /PROCHAIN (V1.1) ============

# Délais fallback en minutes (utilisés quand pas encore de stats)
FALLBACK_DELAYS = {
    "AROME": {
        0: 270,   # 4h30 → dispo ~04h30 Paris
        6: 300,   # 5h00 → dispo ~11h00 Paris
        12: 285,  # 4h45 → dispo ~16h45 Paris
        18: 300,  # 5h00 → dispo ~23h00 Paris
    },
    "ARPEGE": {
        0: 300,   # 5h00 → dispo ~05h00 Paris
        6: 330,   # 5h30 → dispo ~11h30 Paris
        12: 315,  # 5h15 → dispo ~17h15 Paris
        18: 330,  # 5h30 → dispo ~23h30 Paris
    },
    "GFS": {
        0: 270,   # 4h30 → dispo ~04h30 Paris
        6: 300,   # 5h00 → dispo ~11h00 Paris
        12: 285,  # 4h45 → dispo ~16h45 Paris
        18: 300,  # 5h00 → dispo ~23h00 Paris
    },
    "ECMWF": {
        0: 540,   # 9h00 → dispo ~09h00 Paris
        6: 300,   # 5h00 → dispo ~11h00 Paris
        12: 540,  # 9h00 → dispo ~21h00 Paris
        18: 300,  # 5h00 → dispo ~23h00 Paris
    }
}

EMOJI_MAP = {
    "AROME": "⛵",
    "ARPEGE": "🌍",
    "GFS": "🌎",
    "ECMWF": "🇪🇺"
}


# ============ FONCTIONS HELPER POUR /PROCHAIN (V1.1) ============

def round_to_quarter_hour(hour_decimal: float) -> str:
    """Arrondit une heure décimale au quart d'heure le plus proche"""
    hours = int(hour_decimal)
    minutes = (hour_decimal - hours) * 60
    
    # Arrondir au quart d'heure (0, 15, 30, 45)
    rounded_minutes = round(minutes / 15) * 15
    
    # Gérer le cas où on arrondit à 60
    if rounded_minutes == 60:
        hours += 1
        rounded_minutes = 0
    
    # Gérer le dépassement 24h
    hours = hours % 24
    
    return f"{hours:02d}h{rounded_minutes:02d}"


def generate_aide_horaires() -> str:
    """Génère la section horaires de /aide avec stats dynamiques"""
    
    models_info = {
        "AROME": {
            "emoji": "⛵",
            "desc": "(France, très précis)",
            "runs": [0, 6, 12, 18]
        },
        "ARPEGE": {
            "emoji": "🌍",
            "desc": "(Europe/Monde)",
            "runs": [0, 6, 12, 18]
        },
        "GFS": {
            "emoji": "🌎",
            "desc": "(Monde, américain)",
            "runs": [0, 6, 12, 18]
        },
        "ECMWF": {
            "emoji": "🇪🇺",
            "desc": "(Monde, référence)",
            "runs": [0, 6, 12, 18]
        }
    }
    
    result = ""
    has_any_stats = False
    has_any_estimates = False
    
    for model, info in models_info.items():
        result += f"\n**{model}** {info['emoji']} {info['desc']} :\n"
        
        for run_hour in info['runs']:
            # Essayer de récupérer les stats
            stats = get_log_stats(model, run_hour, days=30)
            
            if stats and stats['count'] >= 3:
                # Stats disponibles
                avg_delay = stats['avg_delay']
                count = stats['count']
                
                # Calculer heure de dispo (run_hour + délai)
                dispo_hour = run_hour + (avg_delay / 60)
                dispo_str = round_to_quarter_hour(dispo_hour)
                
                result += f"• Run {run_hour:02d}h → dispo vers {dispo_str} 📊 ({count} obs)\n"
                has_any_stats = True
            else:
                # Fallback hardcodé
                delay = FALLBACK_DELAYS.get(model, {}).get(run_hour)
                
                if delay is not None:
                    dispo_hour = run_hour + (delay / 60)
                    dispo_str = round_to_quarter_hour(dispo_hour)
                    result += f"• Run {run_hour:02d}h → dispo vers {dispo_str} ⏱️\n"
                    has_any_estimates = True
    
    # Footer explicatif
    result += "\n"
    if has_any_stats and has_any_estimates:
        result += "📊 = Délais moyens observés • ⏱️ = Estimations"
    elif has_any_stats:
        result += "📊 = Délais moyens observés (30 derniers jours)"
    else:
        result += "⏱️ = Estimations (collecte de stats en cours)"
    
    return result


# ============ FONCTIONS HELPER POUR /PROCHAINS (V1.1) ============

def calculate_next_run(now: datetime, run_hour: int) -> datetime:
    """Calcule le prochain run_datetime pour une heure donnée"""
    # Créer datetime pour le run aujourd'hui
    today_run = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    # Si déjà passé, prendre demain
    if now >= today_run:
        return today_run + timedelta(days=1)
    return today_run


def get_eta_with_fallback(model: str, run_hour: int, run_datetime: datetime) -> tuple[datetime | None, bool]:
    """
    Retourne (ETA, has_stats).
    has_stats = True si basé sur vraies données, False si fallback
    """
    # Essayer stats réelles
    eta = get_next_run_eta(model, run_hour, run_datetime)
    
    if eta is not None:
        return eta, True
    
    # Fallback hardcodé
    delay_minutes = FALLBACK_DELAYS.get(model, {}).get(run_hour)
    
    if delay_minutes is None:
        # Run pas supporté pour ce modèle
        return None, False
    
    return run_datetime + timedelta(minutes=delay_minutes), False


def format_prochain_message(runs_by_model: dict, show_all: bool = False):
    """Formate le message groupé par modèle"""
    paris_tz = ZoneInfo('Europe/Paris')
    now = datetime.now(timezone.utc)
    
    message = "🔮 **Prochains runs (24h)**\n\n"
    
    if not runs_by_model:
        return "Aucun run prévu dans les 24 prochaines heures."
    
    # Afficher par modèle
    for model, runs in runs_by_model.items():
        if not runs:
            continue
        
        emoji = EMOJI_MAP.get(model, "🌐")
        message += f"{emoji} **{model}**\n"
        
        for run in runs:
            eta = run['eta']
            run_hour = run['run_hour']
            has_stats = run['has_stats']
            
            # Convertir en heure Paris
            eta_paris = eta.astimezone(paris_tz)
            
            # Calculer délai relatif
            delay = eta - now
            hours = int(delay.total_seconds() // 3600)
            minutes = int((delay.total_seconds() % 3600) // 60)
            delay_str = f"dans {hours}h{minutes:02d}"
            
            # Indicateur source
            source_icon = "📊" if has_stats else "⏱️"
            
            message += f"• Run {run_hour:02d} → dispo {eta_paris:%H:%M} ({delay_str}) {source_icon}\n"
        
        message += "\n"
    
    # Footer avec légende
    logs_count = count_logs_for_stats()
    message += "💡 **Prédictions :**\n"
    
    if logs_count >= 30:
        message += f"📊 Moyenne réelle ({logs_count} observations sur 30j)\n"
    elif logs_count > 0:
        message += f"📊 Moyenne réelle ({logs_count} observations)\n"
    else:
        message += "📊 Moyenne réelle (statistiques en cours)\n"
    
    message += "⏱️ Estimation (collecte en cours)"
    
    return message


# ============ FONCTIONS HELPER POUR /LOL (V1.1.2) ============

def get_random_joke():
    """
    Récupère une blague aléatoire depuis l'API blague-api.vercel.app
    Retourne (blague, reponse) ou None en cas d'erreur
    """
    try:
        response = requests.get(
            "https://blague-api.vercel.app/api?mode=global",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        blague = data.get('blague', '').strip()
        reponse = data.get('reponse', '').strip()
        
        return blague, reponse
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API blagues: {e}")
        return None
    except (KeyError, ValueError) as e:
        logger.error(f"Erreur parsing blague: {e}")
        return None


# ============ COMMANDES ============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start - Inscription de l'utilisateur"""
    chat_id = update.message.chat.id
    username = update.message.from_user.username
    
    # Vérifier si c'est un nouvel utilisateur
    existing_user = get_user(chat_id)
    is_new_user = existing_user is None
    
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
/prochains — Prochains runs attendus (ETAs)
/statut — Voir tes abonnements
/derniers — Derniers runs disponibles
/aide — Comprendre les runs météo
/lol — Une blague pour rigoler 😄
/arreter — Se désabonner
    """
    
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    logger.info(f"User {chat_id} ({username}) started the bot (new: {is_new_user})")


async def aide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /aide - Explique le fonctionnement des modèles météo"""
    
    # Générer les horaires dynamiquement (avec stats si disponibles)
    horaires_section = generate_aide_horaires()
    
    aide_text = f"""
📚 **Comment ça marche ?**

Les modèles météo (AROME, GFS...) calculent des prévisions plusieurs fois par jour. Chaque calcul s'appelle un **run**.

🕐 **Pourquoi un délai ?**
Un run "00h" utilise les observations de 00h UTC, mais le calcul prend du temps. Il sort donc quelques heures plus tard.

⏰ **Horaires de disponibilité (heure de Paris) :**
{horaires_section}

💡 **Conseil nav :**
Pour une nav le matin, consulte le run 00h dès qu'il sort (~04h).
Pour une nav l'après-midi, attends le run 06h (~12h).

🔮 **Nouveau :** Utilise /prochains pour voir quand les prochains runs sortiront !

📋 **Commandes :**
/modeles — Choisir les modèles
/horaires — Choisir quels runs recevoir
/prochains — Prochains runs attendus (ETAs)
/statut — Voir tes abonnements
/derniers — Derniers runs disponibles
/lol — Une blague pour rigoler 😄
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


async def prochains_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /prochains [tout] - Affiche les prochains runs attendus"""
    chat_id = update.message.chat.id
    user = get_user(chat_id)
    
    # Détecter si "tout" est demandé
    show_all = len(context.args) > 0 and context.args[0].lower() == "tout"
    
    if show_all:
        # Tous les modèles et runs
        models_to_check = list(MODELS.keys())
        runs_to_check = [0, 6, 12, 18]
    else:
        # Seulement les modèles/runs suivis par l'user
        if not user:
            await update.message.reply_text(
                "Tu n'es pas encore inscrit ! Utilise /start pour commencer."
            )
            return
        
        models_to_check = user['models'] if user['models'] else list(MODELS.keys())
        runs_to_check = user['runs'] if user['runs'] else [6, 12]
    
    # Message d'attente
    wait_msg = await update.message.reply_text("🔮 Calcul des prochains runs...")
    
    # Construire la liste des runs
    now = datetime.now(timezone.utc)
    runs_by_model = {}
    
    for model in models_to_check:
        model_runs = []
        
        for run_hour in runs_to_check:
            # Calculer prochain run datetime
            next_run_dt = calculate_next_run(now, run_hour)
            
            # Obtenir ETA avec fallback
            result = get_eta_with_fallback(model, run_hour, next_run_dt)
            
            if result[0] is None:
                continue
            
            eta, has_stats = result
            
            # Filtrer : seulement les runs dans les 24h à venir
            if now < eta < now + timedelta(hours=24):
                model_runs.append({
                    'run_hour': run_hour,
                    'eta': eta,
                    'has_stats': has_stats
                })
        
        # Trier les runs par heure (chronologique)
        model_runs.sort(key=lambda x: x['eta'])
        
        if model_runs:
            runs_by_model[model] = model_runs
    
    # Formatter le message
    message = format_prochain_message(runs_by_model, show_all)
    
    # Ajouter bouton toggle
    keyboard = []
    if show_all:
        keyboard.append([
            InlineKeyboardButton("👤 Voir mes abonnements", callback_data="prochains_mine")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("🌍 Voir tous les modèles", callback_data="prochains_all")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Envoyer avec bouton
    await wait_msg.edit_text(message, parse_mode="Markdown", reply_markup=reply_markup)


async def lol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /lol - Affiche une blague aléatoire"""
    
    # Message d'attente
    wait_msg = await update.message.reply_text("😄 Cherche une blague...")
    
    # Récupérer une blague
    result = get_random_joke()
    
    if result is None:
        await wait_msg.edit_text(
            "😅 Oups, impossible de récupérer une blague pour le moment.\n"
            "Réessaie dans quelques secondes !"
        )
        return
    
    blague, reponse = result
    
    # Formatter le message en HTML (pour supporter les spoilers)
    if reponse:
        # Blague avec question/réponse (spoiler pour la réponse)
        message = f"😂 <b>Blague du jour :</b>\n\n{blague}\n\n<tg-spoiler>{reponse}</tg-spoiler>"
    else:
        # Blague simple
        message = f"😂 <b>Blague du jour :</b>\n\n{blague}"
    
    await wait_msg.edit_text(message, parse_mode="HTML")
    logger.info(f"Blague envoyée à {update.message.chat.id}")


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
        
        # V1.2.2: Notification admin async (fire-and-forget)
        # Vérifier si c'est un nouvel user (0 modèles avant, 1+ après)
        if models:
            user = get_user(chat_id)
            username = user.get('username') if user else None
            models_str = ", ".join(models)
            
            # Lancer notification en arrière-plan (non-bloquant)
            asyncio.create_task(
                send_admin_notification(
                    context.bot,
                    f"👤 **Utilisateur actif**\n\n"
                    f"Chat ID: `{chat_id}`\n"
                    f"Username: @{username or 'N/A'}\n"
                    f"Modèles: {models_str}",
                    error_type="new_user"
                )
            )
        
        # Répondre immédiatement à l'user (pas d'attente)
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
    
    # ----- PROCHAINS : AFFICHER TOUT -----
    elif data == "prochains_all":
        user = get_user(chat_id)
        if not user:
            await query.answer("Tu dois être inscrit pour utiliser cette fonction.", show_alert=True)
            return
        
        # Tous les modèles et runs
        models_to_check = list(MODELS.keys())
        runs_to_check = [0, 6, 12, 18]
        
        # Recalculer les runs
        now = datetime.now(timezone.utc)
        runs_by_model = {}
        
        for model in models_to_check:
            model_runs = []
            
            for run_hour in runs_to_check:
                next_run_dt = calculate_next_run(now, run_hour)
                result = get_eta_with_fallback(model, run_hour, next_run_dt)
                
                if result[0] is None:
                    continue
                
                eta, has_stats = result
                
                if now < eta < now + timedelta(hours=24):
                    model_runs.append({
                        'run_hour': run_hour,
                        'eta': eta,
                        'has_stats': has_stats
                    })
            
            model_runs.sort(key=lambda x: x['eta'])
            
            if model_runs:
                runs_by_model[model] = model_runs
        
        # Formatter et afficher avec bouton toggle
        message = format_prochain_message(runs_by_model, True)
        keyboard = [[InlineKeyboardButton("👤 Voir mes abonnements", callback_data="prochains_mine")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode="Markdown", reply_markup=reply_markup)
    
    # ----- PROCHAINS : AFFICHER MES ABONNEMENTS -----
    elif data == "prochains_mine":
        user = get_user(chat_id)
        if not user:
            await query.answer("Tu dois être inscrit pour utiliser cette fonction.", show_alert=True)
            return
        
        # Seulement les modèles/runs suivis
        models_to_check = user['models'] if user['models'] else list(MODELS.keys())
        runs_to_check = user['runs'] if user['runs'] else [6, 12]
        
        # Recalculer les runs
        now = datetime.now(timezone.utc)
        runs_by_model = {}
        
        for model in models_to_check:
            model_runs = []
            
            for run_hour in runs_to_check:
                next_run_dt = calculate_next_run(now, run_hour)
                result = get_eta_with_fallback(model, run_hour, next_run_dt)
                
                if result[0] is None:
                    continue
                
                eta, has_stats = result
                
                if now < eta < now + timedelta(hours=24):
                    model_runs.append({
                        'run_hour': run_hour,
                        'eta': eta,
                        'has_stats': has_stats
                    })
            
            model_runs.sort(key=lambda x: x['eta'])
            
            if model_runs:
                runs_by_model[model] = model_runs
        
        # Formatter et afficher avec bouton toggle
        message = format_prochain_message(runs_by_model, False)
        keyboard = [[InlineKeyboardButton("🌍 Voir tous les modèles", callback_data="prochains_all")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode="Markdown", reply_markup=reply_markup)


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
    app.add_handler(CommandHandler("aide", aide_command))
    app.add_handler(CommandHandler("modeles", modeles_command))
    app.add_handler(CommandHandler("horaires", horaires_command))
    app.add_handler(CommandHandler("prochains", prochains_command))
    app.add_handler(CommandHandler("statut", statut_command))
    app.add_handler(CommandHandler("derniers", derniers_command))
    app.add_handler(CommandHandler("lol", lol_command))
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
