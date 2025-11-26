"""
Détection des nouveaux runs de modèles météorologiques
Utilise l'API officielle Météo-France pour AROME et ARPEGE
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
import requests

from config import AROME_API_KEY, ARPEGE_API_KEY

logger = logging.getLogger(__name__)

# Timeouts pour les requêtes HTTP
REQUEST_TIMEOUT = 30

# ============ CACHE MÉMOIRE ============
# Cache des derniers runs connus pour éviter de spammer les APIs
# Structure: {"MODEL": {"run": datetime, "updated_at": datetime}}
_runs_cache: dict[str, dict] = {}
CACHE_TTL = timedelta(minutes=5)


def get_cached_run(model: str) -> datetime | None:
    """Récupère un run depuis le cache s'il est encore valide."""
    if model not in _runs_cache:
        return None
    
    entry = _runs_cache[model]
    age = datetime.now(timezone.utc) - entry["updated_at"]
    
    if age > CACHE_TTL:
        return None  # Cache expiré
    
    return entry["run"]


def set_cached_run(model: str, run_datetime: datetime):
    """Stocke un run dans le cache."""
    _runs_cache[model] = {
        "run": run_datetime,
        "updated_at": datetime.now(timezone.utc),
    }


def get_all_cached_runs() -> dict[str, dict]:
    """
    Retourne tous les runs en cache avec leur âge.
    Pour la commande /lastruns.
    """
    now = datetime.now(timezone.utc)
    result = {}
    
    for model, entry in _runs_cache.items():
        age = now - entry["updated_at"]
        result[model] = {
            "run": entry["run"],
            "age_seconds": int(age.total_seconds()),
            "is_fresh": age <= CACHE_TTL,
        }
    
    return result


def init_cache():
    """
    Initialise le cache au démarrage du bot.
    Récupère le dernier run de chaque modèle.
    """
    logger.info("🔄 Initialisation du cache des runs...")
    
    models = ["AROME", "ARPEGE", "GFS", "ECMWF"]
    
    for model in models:
        try:
            if model == "AROME":
                get_latest_meteofrance_run("AROME", use_cache=False)
            elif model == "ARPEGE":
                get_latest_meteofrance_run("ARPEGE", use_cache=False)
            elif model == "GFS":
                get_latest_gfs_run(use_cache=False)
            elif model == "ECMWF":
                get_latest_ecmwf_run(use_cache=False)
            
            logger.info(f"  ✅ {model} : cache initialisé")
        except Exception as e:
            logger.warning(f"  ⚠️ {model} : échec init cache ({e})")


# Configuration des APIs Météo-France
METEOFRANCE_APIS = {
    "AROME": {
        "base_url": "https://public-api.meteofrance.fr/public/arome/1.0",
        "capabilities_path": "/wms/MF-NWP-HIGHRES-AROME-0025-FRANCE-WMS/GetCapabilities",
        "api_key_getter": lambda: AROME_API_KEY,
    },
    "ARPEGE": {
        "base_url": "https://public-api.meteofrance.fr/public/arpege/1.0",
        "capabilities_path": "/wms/MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WMS/GetCapabilities",
        "api_key_getter": lambda: ARPEGE_API_KEY,
    },
}


# ============ MÉTÉO-FRANCE (AROME / ARPEGE) ============

def get_meteofrance_available_runs(model: str) -> list[datetime]:
    """
    Récupère la liste des runs disponibles pour un modèle Météo-France
    en parsant la réponse GetCapabilities.
    
    Returns:
        Liste de datetimes des runs disponibles, triée du plus récent au plus ancien
    """
    config = METEOFRANCE_APIS.get(model)
    if not config:
        logger.error(f"Modèle {model} non configuré pour Météo-France")
        return []
    
    api_key = config["api_key_getter"]()
    if not api_key:
        logger.warning(f"Pas d'API key pour {model}, skip")
        return []
    
    url = config["base_url"] + config["capabilities_path"]
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "language": "fre",
    }
    headers = {
        "apikey": api_key,
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 401:
            logger.error(f"{model}: API key invalide")
            return []
        
        if response.status_code != 200:
            logger.error(f"{model}: Erreur API {response.status_code}")
            return []
        
        # Parser le XML WMS
        runs = parse_wms_capabilities_for_runs(response.text, model)
        return runs
        
    except requests.RequestException as e:
        logger.error(f"Erreur requête {model}: {e}")
        return []


def parse_wms_capabilities_for_runs(xml_content: str, model: str) -> list[datetime]:
    """
    Parse le XML GetCapabilities WMS pour extraire les runs disponibles.
    
    Le format WMS 1.3.0 contient des dimensions TIME avec les valeurs disponibles.
    """
    runs = []
    
    try:
        # Namespace WMS
        namespaces = {
            'wms': 'http://www.opengis.net/wms',
        }
        
        root = ET.fromstring(xml_content)
        
        # Chercher les éléments Dimension avec name="time" ou "reference_time"
        # Le XML peut avoir différentes structures selon le service
        
        # Méthode 1: Chercher <Dimension name="time">
        for dim in root.iter():
            if dim.tag.endswith('Dimension'):
                dim_name = dim.get('name', '').lower()
                if dim_name in ('time', 'reference_time', 'referencetime'):
                    # Le contenu est une liste de dates séparées par des virgules
                    if dim.text:
                        runs.extend(parse_time_dimension(dim.text))
        
        # Méthode 2: Chercher dans les attributs extent
        for extent in root.iter():
            if extent.tag.endswith('Extent'):
                extent_name = extent.get('name', '').lower()
                if extent_name in ('time', 'reference_time'):
                    if extent.text:
                        runs.extend(parse_time_dimension(extent.text))
        
        # Dédupliquer et trier (plus récent en premier)
        runs = list(set(runs))
        runs.sort(reverse=True)
        
        if runs:
            logger.info(f"{model}: {len(runs)} runs trouvés, dernier: {runs[0]}")
        else:
            logger.warning(f"{model}: Aucun run trouvé dans le XML")
        
        return runs
        
    except ET.ParseError as e:
        logger.error(f"Erreur parsing XML {model}: {e}")
        return []


def parse_time_dimension(time_str: str) -> list[datetime]:
    """
    Parse une chaîne de dimension temporelle WMS.
    
    Formats possibles:
    - Liste: "2025-11-27T00:00:00Z,2025-11-27T06:00:00Z,..."
    - Intervalle: "2025-11-26T00:00:00Z/2025-11-27T18:00:00Z/PT6H"
    """
    runs = []
    time_str = time_str.strip()
    
    # Format intervalle: start/end/period
    if '/' in time_str and time_str.count('/') == 2:
        parts = time_str.split('/')
        try:
            start = parse_iso_datetime(parts[0])
            end = parse_iso_datetime(parts[1])
            period = parse_iso_duration(parts[2])
            
            if start and end and period:
                current = start
                while current <= end:
                    runs.append(current)
                    current += period
        except Exception as e:
            logger.debug(f"Erreur parsing intervalle: {e}")
    
    # Format liste: valeurs séparées par des virgules
    else:
        for value in time_str.split(','):
            value = value.strip()
            if value:
                dt = parse_iso_datetime(value)
                if dt:
                    runs.append(dt)
    
    return runs


def parse_iso_datetime(s: str) -> datetime | None:
    """Parse une date ISO 8601."""
    s = s.strip()
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%MZ",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    
    return None


def parse_iso_duration(s: str) -> timedelta | None:
    """Parse une durée ISO 8601 (ex: PT6H, PT3H, P1D)."""
    s = s.strip().upper()
    
    # Pattern simple pour les durées courantes
    match = re.match(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?', s)
    if match:
        days = int(match.group(1) or 0)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)
        return timedelta(days=days, hours=hours, minutes=minutes)
    
    return None


def check_meteofrance_availability(model: str, run_datetime: datetime) -> bool:
    """
    Vérifie si un run spécifique est disponible pour AROME ou ARPEGE.
    """
    available_runs = get_meteofrance_available_runs(model)
    
    # Normaliser pour comparaison (ignorer les microsecondes)
    run_datetime = run_datetime.replace(microsecond=0)
    if run_datetime.tzinfo is None:
        run_datetime = run_datetime.replace(tzinfo=timezone.utc)
    
    for run in available_runs:
        run = run.replace(microsecond=0)
        if run == run_datetime:
            return True
    
    return False


def get_latest_meteofrance_run(model: str, use_cache: bool = True) -> datetime | None:
    """
    Récupère le dernier run disponible pour un modèle Météo-France.
    Utilise le cache si disponible et use_cache=True.
    """
    # Vérifier le cache d'abord
    if use_cache:
        cached = get_cached_run(model)
        if cached:
            logger.debug(f"{model}: utilisation du cache")
            return cached
    
    # Sinon, requête API
    runs = get_meteofrance_available_runs(model)
    if runs:
        latest = runs[0]  # Déjà trié du plus récent au plus ancien
        set_cached_run(model, latest)
        return latest
    return None


# ============ Wrappers AROME / ARPEGE ============

def check_arome_availability(run_datetime: datetime) -> bool:
    """Vérifie si un run AROME est disponible."""
    return check_meteofrance_availability("AROME", run_datetime)


def check_arpege_availability(run_datetime: datetime) -> bool:
    """Vérifie si un run ARPEGE est disponible."""
    return check_meteofrance_availability("ARPEGE", run_datetime)


def get_expected_arome_run(current_time: datetime) -> datetime | None:
    """Retourne le dernier run AROME disponible (avec cache)."""
    return get_latest_meteofrance_run("AROME", use_cache=True)


def get_expected_arpege_run(current_time: datetime) -> datetime | None:
    """Retourne le dernier run ARPEGE disponible (avec cache)."""
    return get_latest_meteofrance_run("ARPEGE", use_cache=True)


# ============ GFS (NOAA) ============

def check_gfs_availability(run_datetime: datetime) -> bool:
    """
    Vérifie si un run GFS est disponible sur NOMADS.
    """
    try:
        date_str = run_datetime.strftime("%Y%m%d")
        hour_str = run_datetime.strftime("%H")
        
        # Vérifier l'existence du fichier d'analyse (f000)
        url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.f000"
        
        response = requests.head(url, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            logger.info(f"GFS run {run_datetime} disponible")
            set_cached_run("GFS", run_datetime)
            return True
        
        return False
        
    except requests.RequestException as e:
        logger.error(f"Erreur vérification GFS: {e}")
        return False


def get_latest_gfs_run(use_cache: bool = True) -> datetime | None:
    """
    Récupère le dernier run GFS disponible.
    Vérifie les runs récents jusqu'à en trouver un disponible.
    """
    # Vérifier le cache d'abord
    if use_cache:
        cached = get_cached_run("GFS")
        if cached:
            logger.debug("GFS: utilisation du cache")
            return cached
    
    current_time = datetime.now(timezone.utc)
    run_hours = [0, 6, 12, 18]
    
    # Chercher le dernier run disponible
    for days_back in range(2):
        base_date = current_time.date() - timedelta(days=days_back)
        
        for run_hour in reversed(run_hours):
            run_time = datetime(
                base_date.year, base_date.month, base_date.day,
                run_hour, 0, 0, tzinfo=timezone.utc
            )
            
            # Ne pas chercher dans le futur
            if run_time > current_time:
                continue
            
            if check_gfs_availability(run_time):
                return run_time
    
    return None


def get_expected_gfs_run(current_time: datetime) -> datetime | None:
    """
    Retourne le dernier run GFS disponible (avec cache).
    """
    return get_latest_gfs_run(use_cache=True)


# ============ ECMWF ============

def check_ecmwf_file_exists(run_datetime: datetime) -> bool:
    """
    Vérifie si un run ECMWF existe sur le serveur de données ouvertes.
    """
    try:
        date_str = run_datetime.strftime("%Y%m%d")
        hour_str = run_datetime.strftime("%H")
        
        # URL du serveur ECMWF open data
        url = f"https://data.ecmwf.int/forecasts/{date_str}/{hour_str}z/ifs/0p25/oper/"
        
        response = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        
        if response.status_code == 200:
            logger.debug(f"ECMWF run {run_datetime} disponible")
            return True
        
        return False
        
    except requests.RequestException as e:
        logger.debug(f"ECMWF check failed: {e}")
        return False


def get_latest_ecmwf_run(use_cache: bool = True) -> datetime | None:
    """
    Récupère le dernier run ECMWF disponible.
    Vérifie directement sur le serveur de données ouvertes ECMWF.
    """
    # Vérifier le cache d'abord
    if use_cache:
        cached = get_cached_run("ECMWF")
        if cached:
            logger.debug("ECMWF: utilisation du cache")
            return cached
    
    current_time = datetime.now(timezone.utc)
    run_hours = [0, 6, 12, 18]
    
    # ECMWF publie ~7-9h après le run
    # Chercher les runs récents
    for days_back in range(2):
        base_date = current_time.date() - timedelta(days=days_back)
        
        for run_hour in reversed(run_hours):
            run_time = datetime(
                base_date.year, base_date.month, base_date.day,
                run_hour, 0, 0, tzinfo=timezone.utc
            )
            
            # Ne pas chercher dans le futur
            if run_time > current_time:
                continue
            
            # ECMWF dispo ~8h après le run
            expected_availability = run_time + timedelta(hours=8)
            if current_time < expected_availability:
                continue
            
            # Vérifier sur le serveur ECMWF
            if check_ecmwf_file_exists(run_time):
                set_cached_run("ECMWF", run_time)
                logger.info(f"ECMWF dernier run: {run_time}")
                return run_time
    
    return None


def check_ecmwf_availability(run_datetime: datetime) -> bool:
    """Vérifie si un run ECMWF spécifique est disponible."""
    return check_ecmwf_file_exists(run_datetime)


def get_expected_ecmwf_run(current_time: datetime) -> datetime | None:
    """
    Retourne le dernier run ECMWF disponible (avec cache).
    """
    return get_latest_ecmwf_run(use_cache=True)


# ============ FONCTIONS GÉNÉRIQUES ============

def check_model_availability(model: str, run_datetime: datetime) -> bool:
    """Vérifie la disponibilité d'un run pour un modèle donné."""
    checkers = {
        "AROME": check_arome_availability,
        "ARPEGE": check_arpege_availability,
        "GFS": check_gfs_availability,
        "ECMWF": check_ecmwf_availability,
    }
    
    checker = checkers.get(model)
    if checker:
        return checker(run_datetime)
    
    logger.warning(f"Pas de checker pour le modèle {model}")
    return False


def get_expected_run(model: str, current_time: datetime) -> datetime | None:
    """Calcule/récupère le run attendu pour un modèle donné."""
    getters = {
        "AROME": get_expected_arome_run,
        "ARPEGE": get_expected_arpege_run,
        "GFS": get_expected_gfs_run,
        "ECMWF": get_expected_ecmwf_run,
    }
    
    getter = getters.get(model)
    if getter:
        return getter(current_time)
    
    logger.warning(f"Pas de getter pour le modèle {model}")
    return None


def get_all_latest_runs(force_refresh: bool = False) -> dict[str, datetime | None]:
    """
    Récupère le dernier run de chaque modèle.
    Utilise le cache sauf si force_refresh=True.
    
    Returns:
        Dict avec le dernier run pour chaque modèle
    """
    models = ["AROME", "ARPEGE", "GFS", "ECMWF"]
    results = {}
    
    current_time = datetime.now(timezone.utc)
    use_cache = not force_refresh
    
    for model in models:
        if model == "AROME":
            results[model] = get_latest_meteofrance_run("AROME", use_cache=use_cache)
        elif model == "ARPEGE":
            results[model] = get_latest_meteofrance_run("ARPEGE", use_cache=use_cache)
        elif model == "GFS":
            results[model] = get_latest_gfs_run(use_cache=use_cache)
        elif model == "ECMWF":
            results[model] = get_latest_ecmwf_run(use_cache=use_cache)
    
    return results
