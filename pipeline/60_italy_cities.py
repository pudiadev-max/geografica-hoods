"""
60 - Elenco dei comuni italiani con piu' di 30.000 abitanti (Wikidata, CC0, via QLever).

Serve a due cose: i monumenti d'Italia (10_monuments_candidates / 50_monuments_build) e i quartieri da
OpenStreetMap (61_osm_hoods). Per ogni comune: nome italiano, popolazione, coordinate, regione e
identificativo della relazione OpenStreetMap (proprieta' P402 di Wikidata, che evita ricerche per nome).

Le citta' italiane gia' presenti in `cities.json` (Natural Earth: Roma, Milano, Napoli, Torino...) mantengono
il loro `id` e il loro nome, cosi' i monumenti restano condivisi tra i livelli.

Risultato: pipeline/cache/italy_raw.json (grezzo) e app/src/main/assets/italy.json (per l'app).

    python pipeline/60_italy_cities.py
"""
import json, math, os, re, sys, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wiki

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")
RAW = os.path.join(ROOT, "pipeline", "cache", "italy_raw.json")
MIN_POP = 30000


def ascii_name(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def parse_point(p):
    m = re.match(r"POINT\(([-\d.]+) ([-\d.]+)\)", p or "")
    return (float(m.group(2)), float(m.group(1))) if m else (None, None)      # lat, lon


def km(lat1, lon1, lat2, lon2):
    return wiki.km(lat1, lon1, lat2, lon2)


def main():
    rows = wiki.qlever(
        f"SELECT ?c ?pop WHERE {{ ?c wdt:P31 wd:Q747074 . ?c wdt:P1082 ?pop . FILTER(?pop >= {MIN_POP}) }}")
    pop = {r["c"].rsplit("/", 1)[-1]: float(r["pop"]) for r in rows}
    ids = list(pop)
    info = {q: {} for q in ids}
    for i in range(0, len(ids), 80):
        chunk = " ".join("wd:" + q for q in ids[i:i + 80])
        for r in wiki.qlever(f'SELECT ?c ?l WHERE {{ VALUES ?c {{ {chunk} }} ?c rdfs:label ?l . FILTER(LANG(?l)="it") }}'):
            info[r["c"].rsplit("/", 1)[-1]]["name"] = r["l"]
        for r in wiki.qlever(f"SELECT ?c ?o WHERE {{ VALUES ?c {{ {chunk} }} ?c wdt:P402 ?o }}"):
            info[r["c"].rsplit("/", 1)[-1]]["osm"] = int(r["o"])
        for r in wiki.qlever(f"SELECT ?c ?co WHERE {{ VALUES ?c {{ {chunk} }} ?c wdt:P625 ?co }}"):
            info[r["c"].rsplit("/", 1)[-1]]["co"] = r["co"]
        # regione: prima le regioni "normali", poi (Sicilia, Sardegna, Valle d'Aosta...) le sottoclassi
        for closure in ("wdt:P31", "wdt:P31/wdt:P279*"):
            for r in wiki.qlever(
                    f'SELECT ?c ?l WHERE {{ VALUES ?c {{ {chunk} }} ?c wdt:P131+ ?r . ?r {closure} wd:Q16110 . '
                    f'?r rdfs:label ?l FILTER(LANG(?l)="it") }}'):
                info[r["c"].rsplit("/", 1)[-1]].setdefault("region", r["l"])

    ne = [c for c in json.load(open(os.path.join(ASSETS, "cities.json"), encoding="utf8")) if c["iso"] == "IT"]
    # ogni citta' di Natural Earth corrisponde a UN solo comune: il piu' vicino (entro 12 km)
    link = {}
    for c in ne:
        best = min((q for q in ids if "co" in info[q]),
                   key=lambda q: km(*parse_point(info[q]["co"]), c["lat"], c["lon"]))
        if km(*parse_point(info[best]["co"]), c["lat"], c["lon"]) < 12:
            link[best] = c
    out, used = [], set()
    for q in sorted(ids, key=lambda q: -pop[q]):
        x = info[q]
        lat, lon = parse_point(x.get("co"))
        if lat is None or "name" not in x:
            continue
        cid, name = ascii_name(x["name"]) + "@IT", x["name"]
        if q in link:                              # gia' in Natural Earth: stesso id e nome (Rome@IT / Roma)
            cid, name = link[q]["id"], link[q]["name"]
        if cid in used:
            cid = ascii_name(x["name"]) + f"-{q}@IT"
        used.add(cid)
        out.append(dict(id=cid, name=name, ascii=ascii_name(x["name"]), pop=int(pop[q]), lat=round(lat, 4),
                        lon=round(lon, 4), region=x.get("region", ""), qid=q, osm=x.get("osm"),
                        ne=q in link))
    json.dump(out, open(RAW, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    app = [dict(id=c["id"], name=c["name"], pop=c["pop"], lat=c["lat"], lon=c["lon"], region=c["region"])
           for c in out]
    with open(os.path.join(ASSETS, "italy.json"), "w", encoding="utf8") as f:
        json.dump(app, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} comuni, {sum(1 for c in out if c['ne'])} gia' in Natural Earth, "
          f"{sum(1 for c in out if not c['region'])} senza regione")
    print("senza regione:", [c["name"] for c in out if not c["region"]][:12])


if __name__ == "__main__":
    main()
