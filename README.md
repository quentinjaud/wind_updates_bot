# 🚀 Wind Bot V1.1 - Système de Logging des Disponibilités

## 📦 Fichiers à remplacer

1. **database.py** — Base de données avec logging
2. **scheduler.py** — Scheduler avec logging automatique

## ✨ Nouveautés V1.1

### Nouvelle table `run_availability_log`
```sql
CREATE TABLE run_availability_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,              -- AROME, ARPEGE, GFS, ECMWF
    run_hour INTEGER NOT NULL,        -- 0, 6, 12, 18
    run_date TEXT NOT NULL,           -- 2025-11-27
    detected_at TEXT NOT NULL,        -- 2025-11-27T16:45:23Z
    delay_minutes INTEGER NOT NULL,   -- 285
    CONSTRAINT unique_detection UNIQUE(model, run_date, run_hour)
);
```

### Nouvelles fonctions `database.py`

**Pour V1.2 (commande `/prochain`) :**
```python
# Délai moyen sur 30 jours
get_average_delay(model, run_hour, days=30) -> int | None

# ETA prédite pour un run
get_next_run_eta(model, run_hour, run_date) -> datetime | None

# Stats détaillées
get_log_stats(model, run_hour, days=30) -> dict | None

# Cleanup annuel
cleanup_old_logs(days=365) -> int
```

### Modifications `scheduler.py`

**Logging automatique :**
- Capture `detected_at` lors de la détection
- Appelle `log_run_availability()` après notifications
- Log visible : `📊 AROME 12h logged: +285 min`

**Cleanup annuel :**
- 1er janvier à 3h UTC
- Supprime logs >365 jours
- Log visible : `🧹 Cleanup annuel : X logs supprimés`

## 🚀 Déploiement

```bash
# Remplacer les fichiers
cp database.py /ton/projet/
cp scheduler.py /ton/projet/

# Commit et push
git add database.py scheduler.py
git commit -m "Add V1.1: run availability logging system"
git push

# Railway rebuild automatique
```

## ✅ Vérification post-deploy

### Au démarrage (logs Railway)
```
✅ Database initialized
📊 Availability logs: 0
```

### Après premier run détecté
```
✅ AROME: nouveau run 2025-11-27 12:00:00+00:00 détecté !
AROME: 1 utilisateurs à notifier
AROME: 1/1 notifications envoyées
📊 AROME 12h logged: +285 min
```

### Après 24h
- Entre 4 et 16 logs accumulés
- Base de données ~25-30 KB

## 📊 Volume de données

**1 an de logs :**
- ~5 840 logs (4 modèles × 4 runs/jour × 365 jours)
- ~850 KB de données
- Impact Railway : **0€** (négligeable sur 1 GB)

**Cleanup automatique :**
- 1x/an le 1er janvier
- Garde 1 an d'historique max

## 🎯 Utilisation future (V1.2)

Une fois 7 jours de logs collectés, tu pourras créer `/prochain` :

```python
from database import get_next_run_eta
from datetime import datetime, timezone, timedelta

# Prédire AROME 12h demain
tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
eta = get_next_run_eta("AROME", 12, tomorrow)
# → 2025-11-28 16:45:00+00:00 (précision à la minute)
```

**Affichage utilisateur :**
```
🔮 Prochains runs attendus

AROME 12h → Dispo vers 16h45 (dans 2h30)
ARPEGE 12h → Dispo vers 17h12 (dans 2h57)
GFS 12 → Dispo vers 17h38 (dans 3h23)
ECMWF 12z → Dispo vers 21h30 (dans 7h15)

💡 Basé sur 247 observations (30 derniers jours)
```

## 🐛 Dépannage

**Pas de logs "📊 logged" :**
- Vérifier que `log_run_availability` est bien importé
- Vérifier que `detected_at` est capturé avant les notifications

**Erreur au démarrage :**
- Vérifier que la table `run_availability_log` est créée
- Check logs : `📊 Availability logs: 0` doit apparaître

**Stats retournent None :**
- Normal si <3 observations pour le couple (modèle, run)
- Attendre 3+ détections du même run

## 📞 Support

En cas de problème :
1. Vérifier logs Railway pour erreurs
2. Vérifier persistence DB (`Users: X, Last runs: Y` > 0)
3. Attendre 24-48h pour premiers logs significatifs

---

**Version :** 1.1  
**Date :** 27 novembre 2025  
**Validation attendue :** J+7 (7 jours de collecte minimum)
