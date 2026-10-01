"""
61 - Quartieri da OpenStreetMap -> app/src/main/assets/hoods.json

Dati: (c) contributori di OpenStreetMap, licenza ODbL 1.0 (https://www.openstreetmap.org/copyright).
Il file prodotto e' un "database derivato" (geometrie riproiettate e semplificate): va accreditato e reso
disponibile con la stessa licenza (vedi docs/LICENZE.md).

Fonte: l'endpoint SPARQL di QLever su OpenStreetMap (https://qlever.cs.uni-freiburg.de/api/osm-planet), che espone
le geometrie gia' assemblate e le relazioni di contenimento. Overpass (server pubblici) si e' rivelato inutilizzabile
per un'elaborazione di massa: 504 a caso, minuti per citta'. Qui ogni citta' richiede pochi secondi.

Per ogni citta':
  1. prende il confine del comune e tutti i confini che lo intersecano: amministrativi (admin_level 9-11, oppure
     6-11 per le citta' estere) e place=suburb/quarter/neighbourhood/borough;
  2. li riproietta in km locali, li ritaglia sul comune e li raggruppa per livello;
  3. sceglie il livello che "piastrella" meglio il comune: copertura alta, sovrapposizioni assenti, 5-120 zone;
     tutto il resto e' scartato e finisce nel rapporto (pipeline/cache/hoods_report.json);
  4. semplifica (tolleranza proporzionale alla citta') e scrive il formato dell'app.
Le risposte sono in cache (pipeline/cache/osm/): riprendibile.

    python pipeline/61_osm_hoods.py                 # tutte (comuni italiani >= 30.000 ab. + citta' estere)
    python pipeline/61_osm_hoods.py Bologna Torino  # solo alcune, per nome
"""
import json, math, os, sys, time, unicodedata, urllib.parse, urllib.request
import shapely.ops, shapely.wkt
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wiki

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")
CACHE = os.path.join(ROOT, "pipeline", "cache", "osm")
RAW_ITALY = os.path.join(ROOT, "pipeline", "cache", "italy_raw.json")
REPORT = os.path.join(ROOT, "pipeline", "cache", "hoods_report.json")
OUT = os.path.join(ASSETS, "hoods.json")

QL_OSM = "https://qlever.cs.uni-freiburg.de/api/osm-planet"
R = 6371.0088
MIN_POP_ITALY = 30000
MIN_ZONES, MAX_ZONES = 5, 120
MIN_COVERAGE, MAX_OVERLAP = 0.25, 0.06
MIN_CORE_KM2 = 3.0

# Citta' estere gia' presenti nel gioco (Wikidata QID): stesse citta' di prima, ma con dati OpenStreetMap.
FOREIGN = [
    ("Q60", "us"), ("Q90", "fr"), ("Q64", "de"), ("Q2807", "es"), ("Q1741", "at"), ("Q1085", "cz"),
    ("Q727", "nl"), ("Q1748", "dk"), ("Q1761", "ie"), ("Q100", "us"), ("Q1524", "gr"), ("Q72", "ch"),
    ("Q2841", "co"),
]


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


# ------------------------------------------------------------------ QLever (OpenStreetMap)

PRE = """PREFIX osmrel: <https://www.openstreetmap.org/relation/>
PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX ogc: <http://www.opengis.net/rdf#>
"""


def qosm(query, tries=6):
    url = QL_OSM + "?query=" + urllib.parse.quote(PRE + query)
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": wiki.UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (n + 1))
    raise RuntimeError("QLever non risponde: " + str(last))


def fetch(rel_id, levels):
    """Confine del comune e confini candidati che lo intersecano (con geometria WKT), in cache su disco.

    Il filtro sul livello amministrativo si fa qui in Python: su questo endpoint FILTER sulle stringhe
    di admin_level non restituisce righe.
    """
    path = os.path.join(CACHE, f"{rel_id}_ql.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf8"))
    me = f"https://www.openstreetmap.org/relation/{rel_id}"
    city = qosm(f"SELECT ?wkt WHERE {{ osmrel:{rel_id} geo:hasGeometry/geo:asWKT ?wkt }}")
    admin = qosm(
        f'SELECT ?rel ?lvl ?name ?nameit ?wkt WHERE {{ osmrel:{rel_id} ogc:sfIntersects ?rel . '
        f'?rel osmkey:boundary "administrative" ; osmkey:admin_level ?lvl ; osmkey:name ?name ; '
        f'geo:hasGeometry/geo:asWKT ?wkt . OPTIONAL {{ ?rel osmkey:name:it ?nameit }} }}')
    place = qosm(
        f'SELECT ?rel ?pl ?name ?nameit ?wkt WHERE {{ osmrel:{rel_id} ogc:sfIntersects ?rel . '
        f'?rel osmkey:place ?pl ; osmkey:name ?name ; geo:hasGeometry/geo:asWKT ?wkt . '
        f'OPTIONAL {{ ?rel osmkey:name:it ?nameit }} FILTER(?pl IN ("suburb","quarter","neighbourhood","borough")) }}')
    lv = set(levels.split("|"))
    subs = [dict(id=r["rel"], key=r["lvl"], name=r.get("nameit") or r["name"], wkt=r["wkt"])
            for r in admin if r["lvl"] in lv and "/relation/" in r["rel"] and r["rel"] != me]
    subs += [dict(id=r["rel"], key="place:" + r["pl"], name=r.get("nameit") or r["name"], wkt=r["wkt"])
             for r in place if "/relation/" in r["rel"] or "/way/" in r["rel"]]     # linee chiuse comprese
    data = dict(city=city[0]["wkt"] if city else None, subs=subs)
    os.makedirs(CACHE, exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf8"), ensure_ascii=False)
    return data


# ------------------------------------------------------------------ geometria

class Proj:
    """Equirettangolare locale: km, x verso est, y verso nord. Va bene su una citta' (decine di km)."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0, self.k = lat0, lon0, math.cos(math.radians(lat0))

    def __call__(self, lat, lon):
        return R * math.radians(lon - self.lon0) * self.k, R * math.radians(lat - self.lat0)


def shape_from_wkt(wkt, proj):
    """(Multi)poligono proiettato in km da un WKT lon/lat; None se non e' un'area valida."""
    try:
        g = shapely.wkt.loads(wkt)
    except Exception:
        return None
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    g = shapely.ops.transform(lambda x, y, z=None: proj(y, x), g).buffer(0)
    return g if not g.is_empty else None


def choose(city_poly, rels, proj):
    """Il gruppo di zone che piastrella meglio il comune, oppure (None, motivo)."""
    groups = {}
    for rel in rels:
        name = rel["name"].strip()
        if not name:
            continue
        shape = shape_from_wkt(rel["wkt"], proj)
        if shape is None or shape.area <= 0:
            continue
        inside = shape.intersection(city_poly)
        if inside.is_empty or inside.area < 0.4 * shape.area:       # confine di un comune vicino
            continue
        groups.setdefault(rel["key"], []).append((name, inside, rel))
    if not groups:
        return None, "nessun confine interno trovato"
    best, best_score, notes = None, -1.0, []
    for key, zones in groups.items():
        # stesso nome ripetuto: si tiene la zona piu' grande
        uniq = {}
        for n, g, t in zones:
            if n not in uniq or g.area > uniq[n][0].area:
                uniq[n] = (g, t)
        zones = [(n, g, t) for n, (g, t) in uniq.items()]
        total = sum(g.area for _, g, _ in zones)
        union = unary_union([g for _, g, _ in zones]).area
        coverage = union / city_poly.area
        overlap = (total - union) / total if total else 1.0
        # copertura alta, oppure (comuni molto estesi: Ravenna, Forli') un nucleo urbano di almeno 8 zone e 3 km2:
        # come i rioni di Roma nel vecchio dataset, e' una mappa vera del centro, non dell'intero comune
        core = len(zones) >= 8 and union >= MIN_CORE_KM2
        ok = (MIN_ZONES <= len(zones) <= MAX_ZONES and overlap <= MAX_OVERLAP
              and (coverage >= MIN_COVERAGE or core))
        notes.append(f"livello {key}: {len(zones)} zone, copertura {coverage:.0%}, sovrapposizione {overlap:.0%}"
                     + ("" if ok else " (scartato)"))
        if not ok:
            continue
        score = coverage - 2 * overlap - (0.12 if not 8 <= len(zones) <= 60 else 0)
        if score > best_score:
            best, best_score = (key, zones, coverage), score
    if best is None:
        return None, "; ".join(notes)
    return best, "; ".join(notes)


def rings_of(geom):
    """Anelli di un (multi)poligono: esterno antiorario, buchi orari (riempimento nonzero)."""
    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    out = []
    for p in polys:
        if p.is_empty or p.area <= 0:
            continue
        p = orient(p, sign=1.0)
        out.append([[round(x, 2), round(y, 2)] for x, y in p.exterior.coords][:-1])
        for hole in p.interiors:
            out.append([[round(x, 2), round(y, 2)] for x, y in hole.coords][:-1])
    return out


def build(city, data):
    """HoodCity per una citta' {name, iso, lat, lon, osm, levels}, oppure (None, motivo)."""
    proj = Proj(city["lat"], city["lon"])
    city_poly = shape_from_wkt(data["city"], proj) if data.get("city") else None
    if city_poly is None:
        return None, "confine del comune non disponibile"
    picked, notes = choose(city_poly, data["subs"], proj)
    if picked is None:
        return None, notes
    level, zones, coverage = picked
    minx, miny, maxx, maxy = unary_union([g for _, g, _ in zones]).bounds
    span = max(maxx - minx, maxy - miny)
    tol = max(0.01, span * 0.0025)
    out_zones = []
    for name, g, _ in sorted(zones, key=lambda z: z[0]):
        g = g.simplify(tol, preserve_topology=True)
        rings = rings_of(g)
        if not rings:
            continue
        c = g.representative_point() if not g.centroid.within(g) else g.centroid
        out_zones.append(dict(name=name, r=rings, cx=round(c.x, 2), cy=round(c.y, 2), a=round(g.area, 1)))
    if len(out_zones) < MIN_ZONES:
        return None, "troppe zone perse dopo la semplificazione"
    xs = [p[0] for z in out_zones for ring in z["r"] for p in ring]
    ys = [p[1] for z in out_zones for ring in z["r"] for p in ring]
    hood = dict(slug=norm(city["name"]).replace(" ", "-").replace("'", ""), city=city["name"], iso=city["iso"],
                lat=city["lat"], lon=city["lon"],
                extent=[round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                zones=out_zones)
    return hood, f"livello {level}, {len(out_zones)} zone, copertura {coverage:.0%}; " + notes


# ------------------------------------------------------------------ elenco citta'

def foreign_cities():
    out = []
    qids = " ".join("wd:" + q for q, _ in FOREIGN)
    names, osm, co = {}, {}, {}
    for r in wiki.qlever(f'SELECT ?c ?l WHERE {{ VALUES ?c {{ {qids} }} ?c rdfs:label ?l FILTER(LANG(?l)="it") }}'):
        names[r["c"].rsplit("/", 1)[-1]] = r["l"]
    for r in wiki.qlever(f"SELECT ?c ?o WHERE {{ VALUES ?c {{ {qids} }} ?c wdt:P402 ?o }}"):
        osm[r["c"].rsplit("/", 1)[-1]] = int(r["o"])
    for r in wiki.qlever(f"SELECT ?c ?p WHERE {{ VALUES ?c {{ {qids} }} ?c wdt:P625 ?p }}"):
        m = r["p"].removeprefix("POINT(").removesuffix(")").split()
        co[r["c"].rsplit("/", 1)[-1]] = (float(m[1]), float(m[0]))
    for q, iso in FOREIGN:
        if q in osm and q in co:
            out.append(dict(name=names.get(q, q), iso=iso, lat=round(co[q][0], 4), lon=round(co[q][1], 4),
                            osm=osm[q], levels="6|7|8|9|10|11", pop=0))
    return out


def all_cities():
    italy = json.load(open(RAW_ITALY, encoding="utf8"))
    cities = [dict(name=c["name"], iso="it", lat=c["lat"], lon=c["lon"], osm=c["osm"], levels="9|10|11", pop=c["pop"])
              for c in italy if c.get("osm") and c["pop"] >= MIN_POP_ITALY]
    return sorted(cities, key=lambda c: -c["pop"]) + foreign_cities()


def main():
    wanted = {norm(a) for a in sys.argv[1:]}
    cities = [c for c in all_cities() if not wanted or norm(c["name"]) in wanted]
    result = json.load(open(OUT, encoding="utf8")) if (wanted and os.path.exists(OUT)) else []
    report = json.load(open(REPORT, encoding="utf8")) if os.path.exists(REPORT) else {}
    print(f"{len(cities)} citta' da elaborare", flush=True)
    for n, c in enumerate(cities, 1):
        try:
            hood, note = build(c, fetch(c["osm"], c["levels"]))
        except Exception as e:                                       # una citta' che fallisce non ferma le altre
            hood, note = None, f"errore: {type(e).__name__}: {e}"
        report[c["name"]] = dict(ok=hood is not None, note=note)
        if hood:
            result = [h for h in result if h["city"] != c["name"]] + [hood]
        print(f"[{n}/{len(cities)}] {c['name']}: " + (note if len(note) < 150 else note[:150] + "..."), flush=True)
        if n % 10 == 0 or n == len(cities):
            json.dump(report, open(REPORT, "w", encoding="utf8"), ensure_ascii=False, indent=1)
            json.dump(result, open(OUT, "w", encoding="utf8"), ensure_ascii=False, separators=(",", ":"))
        time.sleep(0.3)
    print(f"{len(result)} citta' con quartieri -> {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
