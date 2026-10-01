"""
62 - Nomi "parlanti" per le zone numerate: da "Municipio 9" a "Niguarda · Affori · Bruzzano · Comasina".

Molti municipi e circoscrizioni italiane (Roma, Milano, Napoli, Torino...) hanno solo un numero, che a chi gioca non dice
niente. Per ogni zona con nome generico cerca in OpenStreetMap (ODbL) i quartieri e i rioni (place=suburb/quarter/
neighbourhood, nodi e aree) che ci stanno dentro, li ordina per notorieta' (pagine Wikipedia della voce Wikidata collegata,
poi tipo di luogo) e scrive i primi in `sub`. Il nome numerato resta in `name` (e' la chiave della zona).

Modifica app/src/main/assets/hoods.json sul posto (idempotente: riparte dai nomi generici). Risposte in cache
(pipeline/cache/osm/<relazione>_places.json).

    python pipeline/62_hood_names.py              # tutte le citta' con zone numerate
    python pipeline/62_hood_names.py Milano Roma  # solo alcune
"""
import importlib.util, json, os, re, sys, time
import shapely.geometry as sg
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wiki

spec = importlib.util.spec_from_file_location("hoods61", os.path.join(HERE, "61_osm_hoods.py"))
h61 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h61)

ROOT = os.path.dirname(HERE)
HOODS = os.path.join(ROOT, "app", "src", "main", "assets", "hoods.json")
CACHE = os.path.join(ROOT, "pipeline", "cache", "osm")

MAX_NAMES = 4
MAX_CHARS = 52
# punteggio minimo di un luogo "noto": almeno una pagina Wikipedia collegata (2 punti a pagina) o il tag wikipedia
NOTABLE = 5
TYPE_WEIGHT = {"suburb": 3, "borough": 3, "quarter": 2, "neighbourhood": 1}

# nome generico: numero al posto del nome (italiano e non)
GENERIC = re.compile(
    r"^(municipio|municipalit|circoscrizione|quartiere \d+$|consiglio di zona|so praha|paris \d|\d+η|"
    r"[ivx]+ circoscrizione)", re.I)

# Citta' con zone numerate dove vale la pena (le altre hanno gia' nomi propri)
CITIES = ["Roma", "Milano", "Napoli", "Torino", "Palermo", "Firenze", "Bari", "Messina", "Livorno", "Praga", "Atene", "Parigi"]


def places(rel_id):
    """Luoghi (quartieri, rioni...) dentro il comune: nodi e aree con nome, in cache."""
    path = os.path.join(CACHE, f"{rel_id}_places.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf8"))
    rows = h61.qosm(
        f'SELECT ?x ?pl ?name ?nameit ?nameen ?wd ?wp ?wkt WHERE {{ osmrel:{rel_id} ogc:sfIntersects ?x . '
        f'?x osmkey:place ?pl ; osmkey:name ?name ; geo:hasGeometry/geo:asWKT ?wkt . '
        f'OPTIONAL {{ ?x osmkey:name:it ?nameit }} OPTIONAL {{ ?x osmkey:name:en ?nameen }} '
        f'OPTIONAL {{ ?x osmkey:wikidata ?wd }} OPTIONAL {{ ?x osmkey:wikipedia ?wp }} '
        f'FILTER(?pl IN ("suburb","quarter","neighbourhood","borough")) }}')
    out = [dict(id=r["x"], pl=r["pl"], name=r.get("nameit") or r.get("nameen") or r["name"], wd=r.get("wd", ""),
                wp=bool(r.get("wp")), wkt=r["wkt"]) for r in rows]
    json.dump(out, open(path, "w", encoding="utf8"), ensure_ascii=False)
    return out


def sitelinks(qids):
    """Numero di pagine Wikipedia per voce Wikidata: misura la notorieta' del luogo."""
    qids = sorted({q for q in qids if re.fullmatch(r"Q\d+", q or "")})
    out = {}
    for i in range(0, len(qids), 200):
        chunk = " ".join("wd:" + q for q in qids[i:i + 200])
        for r in wiki.qlever(f"SELECT ?item (COUNT(DISTINCT ?a) AS ?n) WHERE {{ VALUES ?item {{ {chunk} }} "
                             f"?a schema:about ?item }} GROUP BY ?item"):
            out[r["item"].rsplit("/", 1)[-1]] = int(float(r["n"]))
    return out


def zone_geometry(zone):
    """Poligono della zona dagli anelli del file (esterni antiorari, buchi orari)."""
    ext, holes = [], []
    for ring in zone["r"]:
        pg = sg.Polygon(ring)
        if not pg.is_valid:
            pg = pg.buffer(0)
        a = sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                for i in range(len(ring)))
        (ext if a > 0 else holes).append(pg)
    g = unary_union(ext) if ext else sg.Polygon()
    return g.difference(unary_union(holes)) if holes else g


def point_of(wkt, proj):
    import shapely.wkt
    g = shapely.wkt.loads(wkt)
    p = g if g.geom_type == "Point" else g.representative_point()
    x, y = proj(p.y, p.x)
    return sg.Point(x, y)


def clean_zone(city, name):
    """Nome della zona senza ripetere la citta' ("Municipio 8 di Milano" -> "Municipio 8") e in caratteri latini."""
    n = name.strip()
    n = re.sub(r" di (Milano|Napoli|Torino|Firenze|Bari|Livorno|Palermo|Messina)$", "", n)
    n = re.sub(r"^Municipio Roma ", "Municipio ", n)
    n = re.sub(r"^SO Praha (\d+)$", r"Praga \1", n)
    n = re.sub(r"^(\d+)η Κοινότητα Αθηνών$", r"Comunità \1", n)
    n = re.sub(r"^Paris (\d+)(?:e|er) Arrondissement$", r"\1° arrondissement", n)
    return n


def usable_name(name):
    """Scarta il nome della zona stessa ("10th Arrondissement", "Praha 10") e i nomi in alfabeti non latini."""
    if re.fullmatch(r"\d+(st|nd|rd|th|e|er)? Arrondissement", name, re.I) or re.fullmatch(r"Praha[ -]?\d+", name, re.I):
        return False
    return not any(ord(ch) > 0x24F and ch.isalpha() for ch in name)


def short(names, limit=MAX_CHARS):
    """I primi nomi che stanno nel limite, senza doppioni ("Corvetto" e "Lodi - Corvetto" sono lo stesso posto)."""
    out = []
    for n in names:
        k = h61.norm(n)
        if any(h61.norm(o) in k or k in h61.norm(o) for o in out):
            continue
        if len(" · ".join(out + [n])) > limit or len(out) >= MAX_NAMES:
            continue
        out.append(n)
    return " · ".join(out)


def main():
    wanted = {h61.norm(a) for a in sys.argv[1:]}
    hoods = json.load(open(HOODS, encoding="utf8"))
    cities = {c["name"]: c for c in h61.all_cities()}
    for hood in hoods:
        if hood["city"] not in CITIES or (wanted and h61.norm(hood["city"]) not in wanted):
            continue
        zones = [z for z in hood["zones"] if GENERIC.match(z["name"]) or "sub" in z]
        if not zones:
            continue
        info = cities.get(hood["city"])
        if not info:
            print(hood["city"], "- relazione OSM sconosciuta")
            continue
        proj = h61.Proj(hood["lat"], hood["lon"])
        pl = places(info["osm"])
        sl = sitelinks(p["wd"] for p in pl)
        pts = []
        for p in pl:
            try:
                pts.append((p, point_of(p["wkt"], proj)))
            except Exception:
                pass
        zone_names = {h61.norm(z["name"]) for z in hood["zones"]}     # un'altra zona della citta' non e' un quartiere "dentro"
        print(f"{hood['city']}: {len(pl)} luoghi OSM, {sum(1 for p in pl if p['wd'])} con Wikidata", flush=True)
        for z in zones:
            g = zone_geometry(z)
            inside = {}
            for p, pt in pts:
                if g.contains(pt):
                    name = re.sub(r"^Praha-", "", p["name"].strip())
                    if not usable_name(name) or GENERIC.match(name):
                        continue
                    if h61.norm(name) in zone_names or h61.norm(name) == h61.norm(hood["city"]):
                        continue
                    score = sl.get(p["wd"], 0) * 2 + (2 if p["wp"] else 0) + TYPE_WEIGHT.get(p["pl"], 0)
                    k = h61.norm(name)
                    if k not in inside or score > inside[k][0]:
                        inside[k] = (score, name)
            order = sorted(inside.values(), key=lambda t: (-t[0], t[1]))
            # se ci sono almeno due luoghi con pagina Wikipedia/Wikidata, i luoghi senza (lottizzazioni, "Isola 46") restano fuori
            notable = [n for sc, n in order if sc >= NOTABLE]
            ranked = notable if len(notable) >= 2 else [n for _, n in order]
            z["sub"] = short(ranked)
            z["name"] = clean_zone(hood["city"], z["name"])
            print(f"   {z['name']:<24} {len(inside):>3} luoghi -> {z['sub']}")
        time.sleep(0.3)
    json.dump(hoods, open(HOODS, "w", encoding="utf8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
