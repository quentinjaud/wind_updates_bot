# Wind Bot 🌊⛵

Bot Telegram qui envoie des notifications push quand de nouveaux runs de modèles météorologiques sont disponibles.

**Version actuelle :** 0.9 (MVP en test)  
**Statut :** 🟢 Déployé et opérationnel  
**Bot Telegram :** [@wind_updates_bot](https://t.me/wind_updates_bot)

---

## Table des matières

- [Fonctionnalités](#-fonctionnalités)
- [Commandes](#-commandes-telegram)
- [Modèles météo](#-modèles-météo-supportés)
- [Horaires de disponibilité](#-horaires-de-disponibilité)
- [Architecture](#-architecture)
- [Performance & Limites](#-performance--limites)
- [Roadmap](#-roadmap)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Contribution](#-contribution)
- [FAQ](#-faq)
- [Licence](#-licence)

---

## ✨ Fonctionnalités

- **Notifications push** : Reçois une alerte dès qu'un nouveau run est calculé et publié
- **4 modèles supportés** : AROME, ARPEGE, GFS, ECMWF
- **Personnalisation** : Choisis les modèles et les heures de run qui t'intéressent
- **Runs de jour par défaut** : Pas de notification nocturne sauf si tu le demandes
- **Consultation** : Vérifie à tout moment les derniers runs disponibles
- **Cache intelligent** : Limite les requêtes API (cache 5 min)
- **Multi-utilisateurs** : Chacun ses préférences

---

## 📱 Commandes Telegram

| Commande | Description |
|----------|-------------|
| `/start` | S'inscrire au bot |
| `/aide` | Comprendre les runs météo et leurs horaires |
| `/modeles` | Choisir les modèles météo à suivre |
| `/horaires` | Choisir les runs (00h, 06h, 12h, 18h) |
| `/statut` | Voir ses abonnements actuels |
| `/derniers` | Afficher les derniers runs disponibles |
| `/arreter` | Se désabonner des notifications |

---

## 🌍 Modèles météo supportés

| Modèle | Source | Résolution | Zone | Runs | Utilisation |
|--------|--------|------------|------|------|-------------|
| **AROME** | Météo-France | 1.3 km | France | 00h, 03h, 06h, 12h, 18h | Navigation côtière France, très précis |
| **ARPEGE** | Météo-France | 0.1° | Europe/Monde | 00h, 06h, 12h, 18h | Navigation moyenne distance |
| **GFS** | NOAA | 0.25° | Monde | 00h, 06h, 12h, 18h | Navigation hauturière |
| **ECMWF** | Centre Européen | 0.25° | Monde | 00h, 06h, 12h, 18h | Référence qualité |

---

## ⏰ Horaires de disponibilité

Les modèles météo sont calculés à des heures précises (00h, 06h, 12h, 18h UTC), mais le calcul prend du temps. Voici les horaires **moyens** de disponibilité (heure de Paris) :

| Run | AROME | ARPEGE | GFS | ECMWF |
|-----|-------|--------|-----|-------|
| 00h | ~03h45 🌙 | ~04h50 🌙 | ~04h 🌙 | ~08h ☀️ |
| 06h | ~12h10 ☀️ | ~11h35 ☀️ | ~10h ☀️ | ~14h ☀️ |
| 12h | ~16h55 ☀️ | ~16h25 ☀️ | ~16h ☀️ | ~20h 🌙 |
| 18h | ~00h10 🌙 | ~23h35 🌙 | ~22h 🌙 | ~02h 🌙 |

**Par défaut**, les nouveaux utilisateurs sont abonnés aux runs **06h** et **12h** uniquement (notifications vers midi et 17h, pas de réveil nocturne).

---

## 🏗️ Architecture

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────┐
│                   SOURCES MÉTÉO                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ Météo-France│  │    ECMWF     │  │   NOAA    │  │
│  │  (API WMS)  │  │ (HTTP check) │  │ (NOMADS)  │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  │
└─────────┼────────────────┼────────────────┼────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                   ┌───────▼────────┐
                   │   Wind Bot     │
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

### Composants

#### 1. **Détection des runs** (`checker.py`)
- Vérifie la disponibilité de chaque modèle
- **AROME/ARPEGE :** Parse le XML GetCapabilities de l'API Météo-France
- **GFS :** Vérifie l'existence du fichier via HTTP HEAD sur NOMADS
- **ECMWF :** Vérifie l'existence du répertoire via HTTP HEAD sur data.ecmwf.int
- Cache mémoire 5 minutes pour éviter le spam API

#### 2. **Scheduler** (`scheduler.py`)
- Boucle de vérification toutes les **15 minutes**
- Pour chaque modèle :
  1. Récupère le dernier run disponible
  2. Compare avec le dernier run notifié (SQLite)
  3. Si nouveau run → notifie les utilisateurs abonnés
- Rate limiting Telegram : 0.05s entre chaque notification

#### 3. **Base de données** (`database.py`)
- **Table `users` :** chat_id, modèles suivis, runs suivis, statut actif
- **Table `last_runs` :** dernier run notifié par modèle (évite les doublons)
- Stockage des datetimes en ISO 8601 string (timezone-safe)

#### 4. **Bot Telegram** (`bot.py`)
- Handlers de commandes (françaises)
- Interface boutons inline pour personnalisation
- Gestion multi-utilisateurs avec préférences individuelles

### Flux de notification

```
1. Scheduler se réveille (toutes les 15 min)
2. Pour chaque modèle (AROME, ARPEGE, GFS, ECMWF) :
   a. Appel API météo pour récupérer dernier run
   b. Vérification cache (5 min) → si frais, skip API
   c. Comparaison avec last_run en base
   d. Si nouveau run détecté :
      - Récupération liste users abonnés (modèle + run_hour)
      - Envoi notification push via Telegram
      - Sauvegarde last_run en base
3. Attente 15 minutes
4. Retour à l'étape 1
```

---

## 📊 Performance & Limites

### Latences mesurées

| Métrique | Valeur | Notes |
|----------|--------|-------|
| Vérification d'un modèle | 2-5s | Dépend de l'API |
| Cycle complet (4 modèles) | 10-20s | Avec sleeps entre modèles |
| Latence notification | <10min | Après disponibilité run |
| Uptime | >99% | (objectif V1.1) |

### Limites actuelles

- **Délai de détection :** 15 minutes max (intervalle du scheduler)
- **Cache :** 5 minutes (peut retarder la détection si run sort juste après une vérification)
- **SQLite :** Limité à ~1000 utilisateurs (au-delà, envisager PostgreSQL)
- **Pas de retry :** Si API down, attente prochaine itération (15 min)
- **Pas de backup automatique** (prévu V1.1)

### Rate limiting APIs

- **Météo-France :** Pas de limite connue, cache 5 min par sécurité
- **NOAA NOMADS :** Pas de limite pour HTTP HEAD
- **ECMWF :** Pas de limite pour vérification répertoire
- **Telegram :** 30 msg/sec max → Sleep 0.05s entre notifications

---

## 🗺️ Roadmap

### ✅ V0.9 - MVP (Terminée)
- ✅ Bot fonctionnel avec commandes françaises
- ✅ Détection 4 modèles (AROME, ARPEGE, GFS, ECMWF)
- ✅ Notifications push multi-utilisateurs
- ✅ Personnalisation modèles + runs
- ✅ Runs par défaut jour uniquement
- ✅ Déploiement Railway

### 🔄 V1.0 - Validation (En cours)
- 🔄 Tests notifications push conditions réelles
- 🔄 Monitoring logs Railway 48h
- ⏳ Validation uptime 1 semaine
- ⏳ 5+ utilisateurs actifs

### 📋 V1.1 - Qualité (Prochaine)
- ⏳ **Commande `/prochain`** : ETA du prochain run par modèle
- ⏳ **Collecte métriques** : Logger heures réelles de disponibilité
- ⏳ **Stats publiques** : Délais moyens observés par modèle
- ⏳ **Backup automatique** : Sauvegarde quotidienne SQLite
- ⏳ **Tests unitaires** : Coverage >80%

### 🔮 V1.2 - Confort (Futur)
- ⏳ **Mode silencieux** : Plages horaires sans notification
- ⏳ **Historique** : Liste des dernières notifications reçues
- ⏳ **AROME 03h** : Ajouter le run 03h (actuellement non suivi)
- ⏳ **Filtres avancés** : Notifier uniquement si changement significatif

### 🌐 V1.3+ - Extension (Backlog)
- ⏳ **Multi-langue** : EN, ES
- ⏳ **Timezone utilisateur** : Affichage heures locales
- ⏳ **API publique** : Endpoint REST pour consulter derniers runs
- ⏳ **Webhook mode** : Alternative au polling
- ⏳ **Intégration Discord** : Support autre plateforme

---

## 🛠️ Installation

### Prérequis

- Python 3.11+
- Compte Telegram
- Token bot Telegram (via [@BotFather](https://t.me/BotFather))
- Clés API Météo-France (gratuites sur [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr))

### Installation locale

```bash
# Cloner le repo
git clone https://github.com/quentinjaud/wind_updates_bot.git
cd wind_updates_bot

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
4. Railway détecte automatiquement le `Procfile`
5. Déployer

Le bot démarre automatiquement en mode `worker` (pas de port HTTP).

---

## ⚙️ Configuration

### Variables d'environnement

| Variable | Obligatoire | Description | Exemple |
|----------|-------------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token du bot Telegram | `123456:ABC-DEF...` |
| `AROME_API_KEY` | ✅ | Clé API Météo-France AROME | `eyJhbGciOiJ...` |
| `ARPEGE_API_KEY` | ✅ | Clé API Météo-France ARPEGE | `eyJhbGciOiJ...` |
| `DATABASE_PATH` | ❌ | Chemin fichier SQLite | `bot.db` (défaut) |

### Obtenir les tokens

#### Token Telegram
1. Ouvrir [@BotFather](https://t.me/BotFather) sur Telegram
2. Envoyer `/newbot`
3. Suivre les instructions (nom du bot, username)
4. Copier le token fourni

#### Clés API Météo-France
1. Créer un compte sur [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr)
2. Aller dans "Mes API" → "AROME" → S'abonner (gratuit)
3. Générer un token (type "API Key")
4. Répéter pour ARPEGE

**Note :** Les APIs AROME et ARPEGE sont gratuites, sans limite de requêtes connue.

---

## 🤝 Contribution

Les contributions sont les bienvenues ! Voici comment participer :

### Proposer une amélioration

1. **Ouvrir une issue** sur GitHub avec :
   - Description du besoin
   - Cas d'usage
   - Proposition de solution (optionnel)

2. Attendre validation avant de développer

### Soumettre du code

1. **Fork** le repo
2. Créer une **branche** : `git checkout -b feature/ma-fonctionnalite`
3. **Développer** en respectant les conventions du projet :
   - Commandes en français
   - Logs informatifs
   - Gestion d'erreurs
   - Type hints Python
4. **Tester** localement
5. **Commit** : `git commit -m "Ajout: ma fonctionnalité"`
6. **Push** : `git push origin feature/ma-fonctionnalite`
7. Ouvrir une **Pull Request**

### Conventions de code

- Nommage : snake_case pour variables/fonctions
- Logs : `logger.info()`, pas de `print()`
- Timezone : toujours UTC en interne
- Datetimes SQLite : stockage en ISO string

Voir [`instructions-projet.md`](instructions-projet.md) pour les conventions complètes.

### Signaler un bug

1. Vérifier que le bug n'est pas déjà signalé
2. Ouvrir une issue avec :
   - Description du problème
   - Étapes pour reproduire
   - Comportement attendu vs observé
   - Logs si pertinent

---

## ❓ FAQ

### Le bot fonctionne-t-il 24/7 ?

Oui, le bot est hébergé sur Railway et fonctionne en continu. Il vérifie les modèles toutes les 15 minutes.

### Combien de temps après le run reçois-je la notification ?

Entre 0 et 15 minutes après que le run soit disponible sur les serveurs météo. Le délai dépend du moment où tombe la vérification du scheduler.

### Puis-je être notifié pour tous les runs (y compris la nuit) ?

Oui, utilise la commande `/horaires` et active les runs 00h et 18h. Attention, tu recevras des notifications la nuit (vers 3h-4h et 23h-00h).

### Le bot est-il gratuit ?

Oui, 100% gratuit et sans publicité. Le projet est open-source et hébergé gracieusement sur Railway (free tier).

### Quelles données sont stockées sur moi ?

Le bot stocke uniquement :
- Ton chat_id Telegram (nécessaire pour t'envoyer des notifications)
- Ton username Telegram (pour debug si nécessaire)
- Tes préférences (modèles et runs suivis)

Aucune donnée n'est vendue ou partagée. Voir [`PRIVACY.md`](PRIVACY.md) pour les détails.

### Puis-je héberger ma propre instance du bot ?

Oui, le code est open-source. Voir la section [Installation](#-installation).

### Le bot fonctionne-t-il en dehors de France ?

Oui, le bot fonctionne partout où Telegram fonctionne. Par contre :
- **AROME** couvre uniquement la France
- **ARPEGE/GFS/ECMWF** couvrent le monde entier

### Comment contribuer au projet ?

Voir la section [Contribution](#-contribution). Les contributions sont bienvenues (code, doc, idées, bugs) !

### Y aura-t-il d'autres modèles à l'avenir ?

Peut-être ! Les candidats :
- **ICON** (DWD allemand)
- **WRF** (modèles régionaux)
- **Autres sources ECMWF** (ENS, HRES)

Ouvre une issue pour proposer un modèle.

### Le bot peut-il m'envoyer les fichiers GRIB ?

Non, le bot notifie uniquement de la **disponibilité** d'un run. Pour télécharger les fichiers GRIB, utilise les sites officiels (Météo-France, Windy, etc.).

---

## 📁 Structure du projet

```
wind_updates_bot/
├── bot.py              # Handlers Telegram (commandes, boutons)
├── checker.py          # Détection des runs (APIs météo, cache)
├── scheduler.py        # Vérification périodique (toutes les 15 min)
├── database.py         # Accès SQLite (users, last_runs)
├── config.py           # Configuration (tokens, modèles)
├── requirements.txt    # Dépendances Python
├── Procfile            # Config Railway
├── README.md           # Cette doc
├── PRIVACY.md          # Politique de confidentialité
└── LICENSE             # Licence MIT
```

---

## 🧑‍💻 Auteur

**Quentin Jaud** — Instructeur voile aux Glénans, navigateur et développeur

- **Site web :** [origami-aventures.org](https://origami-aventures.org)
- **GitHub :** [@quentinjaud](https://github.com/quentinjaud)
- **Contact :** Via GitHub issues ou Telegram

---

## 📜 Licence

Ce projet est sous licence **MIT** — voir le fichier [LICENSE](LICENSE) pour les détails.

En résumé : tu peux utiliser, modifier et distribuer ce code librement, à condition de conserver la notice de copyright.

---

## 🙏 Remerciements

- **Météo-France** pour les APIs ouvertes (AROME, ARPEGE)
- **NOAA** pour les données GFS en accès libre
- **ECMWF** pour les données open data
- **Communauté Telegram** pour l'excellente librairie python-telegram-bot
- **Railway** pour l'hébergement gratuit
- **Claude (Anthropic)** pour l'assistance au développement 🤖

---

## 📈 Statistiques du projet

![GitHub stars](https://img.shields.io/github/stars/quentinjaud/wind_updates_bot?style=social)
![GitHub forks](https://img.shields.io/github/forks/quentinjaud/wind_updates_bot?style=social)
![GitHub issues](https://img.shields.io/github/issues/quentinjaud/wind_updates_bot)
![GitHub license](https://img.shields.io/github/license/quentinjaud/wind_updates_bot)

---

**Dernière mise à jour :** 27 novembre 2025  
**Version :** 0.9 (MVP en test)

⛵ **Bon vent !** 🌊
