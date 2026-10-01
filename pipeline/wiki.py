"""
Utilita' condivise per parlare con Wikipedia/Wikidata in modo educato:
User-Agent identificabile, pausa minima tra le richieste, ripetizione su 429/503 con attesa.
Solo libreria standard.
"""
import json, math, time, urllib.error, urllib.parse, urllib.request

UA = "GeoGrafica-pipeline/0.1 (personal educational project)"
_last = [0.0]
MIN_GAP = 0.25  # secondi tra due richieste


def get_json(url, tries=6):
    for n in range(tries):
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 503):
                delay = int(e.headers.get("Retry-After") or 5 * (n + 1))
                time.sleep(min(delay, 120))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(3 * (n + 1))
    return None


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def rest_summary(lang, title):
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"), safe="")
    return get_json(url)


def find_page(titles, lat, lon, max_km):
    """Prima pagina (it poi en) il cui punto e' entro `max_km` dal soggetto: evita gli omonimi."""
    for lang in ("it", "en"):
        for t in titles:
            d = rest_summary(lang, t)
            if not d or d.get("type") != "standard":
                continue
            c = d.get("coordinates")
            if c and km(lat, lon, c["lat"], c["lon"]) <= max_km:
                return lang, d
    return None, None


def wb_entities(ids, props="claims|labels|sitelinks|descriptions", langs="it|en"):
    """wbgetentities a blocchi di 50."""
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        url = ("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&ids=" + "|".join(chunk)
               + "&props=" + props + "&languages=" + langs)
        d = get_json(url)
        if d and "entities" in d:
            out.update(d["entities"])
    return out


QLEVER = "https://qlever.cs.uni-freiburg.de/api/wikidata"
QPREFIX = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
"""


def qlever(query, tries=5):
    """SPARQL su QLever (Wikidata): righe come lista di dict {variabile: valore}."""
    url = QLEVER + "?query=" + urllib.parse.quote(QPREFIX + query)
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]
        except Exception:
            time.sleep(3 * (n + 1))
    return []
