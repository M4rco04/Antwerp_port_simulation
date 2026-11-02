"""Download the berths (ligplaatsen) of the Port of Antwerp-Bruges harbour master's map.

Source: webapps.portofantwerpbruges.com/arcgis/rest/services/extern/havenmeesterkaart/MapServer,
layer 58 "ligplaatsen" (public). Every berth polygon with the harbour master's data; the Dutch
field names are written as plain ASCII names:

    LPL_UN, LPL, NUMMER, TERMINAL, HOEK, TYPE, ISRS   as in slots_cords (same berth ids)
    max_draught_m          maximaal toegelaten diepgang: the draught allowed at the berth
    sounded_depth_taw_m    geinterpreteerde gepeilde diepte: bed level from soundings, m TAW (negative)
    design_depth_taw_m     theoretische diepte: design bed level, m TAW
    min_ukc_m              minimale UKC: under-keel clearance the allowed draught keeps
    max_loa_m, max_beam_m  maximum ship length / beam (where the harbour master sets one)
    max_moored_width_m, max_moored_length_m, mooring_side (stuurboord / bakboord), swing_min
    berth_length_m, category (zeevaart / binnenvaart), quay_type (Conventioneel, Tanker, Container,
    Gemengd, wachtkaai, nvt), berth_type (Stukgoed kaai, Tankinstelling, Container terminal, ...)

Placeholders (-99.99, draughts outside 0-25 m) are written as null.

Usage:
    py src/environment/fetch_berth_data.py
Writes data/berths/havenmeester_ligplaatsen.geojson.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "berths" / "havenmeester_ligplaatsen.geojson"
LAYER = "https://webapps.portofantwerpbruges.com/arcgis/rest/services/extern/havenmeesterkaart/MapServer/58"

log = logging.getLogger("berths")

# source field (accents and the "h_lpl." prefix stripped) -> name in the output
FIELDS = {
    "LPL_UN": "LPL_UN", "LPL": "LPL", "NUMMER": "NUMMER", "TERMINAL": "TERMINAL", "HOEK": "HOEK", "TYPE": "TYPE",
    "ISRS": "ISRS", "RELATED_ISRS": "RELATED_ISRS", "LPL_VOLGEND": "LPL_VOLGEND", "POSITIE_VOLGEND": "POSITIE_VOLGEND",
    "maximaal_toegelaten_diepgang__m_": "max_draught_m",
    "geinterpreteerde_gepeilde_diepte__mTAW_": "sounded_depth_taw_m",
    "theoretische_diepte__mTAW_": "design_depth_taw_m",
    "minimale_UKC__m_": "min_ukc_m",
    "maximaal_toegelaten_scheepslengte__m_": "max_loa_m",
    "maximaal_toegelaten_scheepsbreedte__m_": "max_beam_m",
    "maximale_meerbreedte__m_": "max_moored_width_m",
    "maximale_meerlengte__m_": "max_moored_length_m",
    "verplichte_meerzijde": "mooring_side",
    "zwaaitijd__min_": "swing_min",
    "ligplaatslengte__m_": "berth_length_m",
    "ligplaatscategorie": "category",
    "kaaitype": "quay_type",
    "ligplaatstype": "berth_type",
    "vaarwegsectiecode": "fairway_section",
}
NUMERIC = ("max_draught_m", "sounded_depth_taw_m", "design_depth_taw_m", "min_ukc_m", "max_loa_m", "max_beam_m",
           "max_moored_width_m", "max_moored_length_m", "swing_min", "berth_length_m", "HOEK")


def plain(name):
    name = name.split(".")[-1]
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def number(value):
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None if v <= -99 else v


def clean(props):
    out = {}
    for k, v in props.items():
        name = FIELDS.get(plain(k))
        if name is None or name in out and out[name] not in (None, ""):
            continue
        if isinstance(v, str):
            v = v.strip() or None
        out[name] = number(v) if name in NUMERIC else v
    d = out.get("max_draught_m")
    if d is not None and not 0 < d < 25:
        out["max_draught_m"] = None
    for k in ("sounded_depth_taw_m", "design_depth_taw_m"):
        if out.get(k) is not None and out[k] > 5:                # a bed level above TAW +5 m is not a berth
            out[k] = None
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    query = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": 4326,
                                    "f": "geojson"})
    with urllib.request.urlopen(f"{LAYER}/query?{query}", timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"])
    features = []
    for f in data["features"]:
        if not f.get("geometry"):
            continue
        p = clean(f["properties"])
        if not p.get("LPL_UN"):                                  # a few berths have no id: build one
            p["LPL_UN"] = f"ANTW_{p['LPL']}" if p.get("LPL") else f"HM_{f.get('id')}"
        features.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "name": "havenmeester_ligplaatsen",
                               "source": LAYER, "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "features": features}, ensure_ascii=False), encoding="utf-8")
    with_draught = sum(f["properties"].get("max_draught_m") is not None for f in features)
    log.info("%d berths (%d with an allowed draught) -> %s", len(features), with_draught, OUT)


if __name__ == "__main__":
    main()
