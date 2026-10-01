# GeoGrafica — confini dei quartieri (da OpenStreetMap)

Database dei confini dei quartieri di 46 città (35 italiane), usato dal livello *Quartieri* dell'app Android **GeoGrafica**.
È un **database derivato da OpenStreetMap** e, come tale, è offerto con la stessa licenza.

## Licenza e attribuzione

- Dati: **© contributori di OpenStreetMap**, licenza [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/)
  (testo in `LICENSE`). Informazioni sul copyright di OSM: <https://www.openstreetmap.org/copyright>.
- Chi riutilizza `hoods.json` deve citare OpenStreetMap, mantenere la stessa licenza per i database derivati e rendere
  disponibili le modifiche (share-alike), secondo i termini dell'ODbL.
- Estrazione eseguita il 2026-09-30 (attraverso l'endpoint SPARQL di [QLever](https://qlever.cs.uni-freiburg.de/osm-planet) su OpenStreetMap).
- Gli script in `pipeline/` sono pubblicati per riproducibilità; non è stata scelta una licenza per il codice.

## Contenuto

`hoods.json`: lista di città. Per ciascuna:

| campo | significato |
|---|---|
| `slug`, `city`, `iso` | identificativo, nome (italiano), codice paese a due lettere |
| `lat`, `lon` | centro della città (gradi) |
| `extent` | riquadro `[x0, y0, x1, y1]` in km, nel sistema locale sotto |
| `zones[]` | quartieri: `name`, `r` (anelli: il primo è il contorno, gli altri i buchi), `cx`/`cy` (centroide, km), `a` (area, km²) |

Le coordinate sono in **km** in una proiezione equirettangolare locale centrata su (`lat`, `lon`), con y verso nord. I contorni
sono semplificati (tolleranza proporzionale alla dimensione della città): servono a un gioco, non alla cartografia di precisione.

## Come sono scelte le zone

Per ogni città si prendono i confini che intersecano il comune (amministrativi `admin_level` 9–11, 6–11 per le città
estere, e aree `place=suburb|quarter|neighbourhood|borough`), si ritagliano sul comune e si raggruppano per livello. Si sceglie
il livello che copre meglio il comune senza sovrapposizioni (5–120 zone); le città senza un livello adatto sono escluse. In circa
95 comuni italiani sopra i 30.000 abitanti OSM ha i quartieri solo come punti e non come poligoni: sono fuori.

## Rigenerare

```
pip install shapely
python pipeline/60_italy_cities.py   # elenco dei comuni italiani da Wikidata (QLever)
python pipeline/61_osm_hoods.py      # scrive app/src/main/assets/hoods.json (copia pubblicata qui in hoods.json)
```

## Città incluse (46, 661 zone)

| Città | Paese | Zone |
|---|---|---|
| Roma | IT | 15 |
| Milano | IT | 9 |
| Napoli | IT | 10 |
| Torino | IT | 9 |
| Palermo | IT | 8 |
| Genova | IT | 9 |
| Bologna | IT | 6 |
| Firenze | IT | 5 |
| Bari | IT | 5 |
| Catania | IT | 6 |
| Verona | IT | 8 |
| Venezia | IT | 6 |
| Messina | IT | 6 |
| Trieste | IT | 7 |
| Parma | IT | 13 |
| Brescia | IT | 33 |
| Prato | IT | 9 |
| Modena | IT | 21 |
| Reggio Emilia | IT | 67 |
| Livorno | IT | 7 |
| Cagliari | IT | 31 |
| Bergamo | IT | 8 |
| Trento | IT | 12 |
| Bolzano | IT | 5 |
| Cesena | IT | 12 |
| Brindisi | IT | 10 |
| Grosseto | IT | 8 |
| Imola | IT | 12 |
| Viterbo | IT | 15 |
| Faenza | IT | 5 |
| Siena | IT | 32 |
| Campobasso | IT | 9 |
| San Benedetto del Tronto | IT | 16 |
| Merano | IT | 14 |
| Sassuolo | IT | 11 |
| New York | US | 5 |
| Parigi | FR | 20 |
| Berlino | DE | 12 |
| Madrid | ES | 21 |
| Vienna | AT | 23 |
| Praga | CZ | 22 |
| Amsterdam | NL | 8 |
| Boston | US | 30 |
| Atene | GR | 7 |
| Zurigo | CH | 34 |
| Bogotà | CO | 20 |
