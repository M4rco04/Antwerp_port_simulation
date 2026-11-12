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

The nautical port map's layer "Tankvaart" (service LIGPL, layer 7) gives the stretches of quay where inland tank
barges may lie, by the blue cones they may carry (1 no cone, 3 no cone with 6 m from vehicles, 2 at most one,
5 only one-cone barges, 4 at most two). The same map's layer 20 "bedrijven" (companies) gives each plot of land its company and activity (natte bulk,
raffinage, chemie, containers, droge bulk, ...). The berth catalogue uses the plot behind a berth to tell tanker
berths where the harbour master's data gives no berth type (terminals.py).

Usage:
    py src/environment/fetch_berth_data.py                # berths and plots
    py src/environment/fetch_berth_data.py --plots-only    # plots and tank-barge stretches
Writes data/berths/havenmeester_ligplaatsen.geojson, havenmeester_bedrijven.geojson and tankvaart.geojson.
"""

from __future__ import annotations

import argparse
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
PLOTS_OUT = ROOT / "data" / "berths" / "havenmeester_bedrijven.geojson"
PLOTS_LAYER = "https://webapps.portofantwerpbruges.com/arcgis/rest/services/extern/havenmeesterkaart/MapServer/20"
TANK_OUT = ROOT / "data" / "berths" / "tankvaart.geojson"
TANK_LAYER = "https://webapps.portofantwerpbruges.com/arcgis/rest/services/extern/LIGPL/MapServer/7"
TANK_CLASSES = {1: "no cone", 3: "no cone, 6 m from vehicles", 2: "at most one blue cone",
                5: "only one-cone barges", 4: "at most two blue cones"}

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


def query(layer, fields="*"):
    q = urllib.parse.urlencode({"where": "1=1", "outFields": fields, "returnGeometry": "true", "outSR": 4326,
                                "f": "geojson"})
    with urllib.request.urlopen(f"{layer}/query?{q}", timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def fetch_plots():
    """The company plots (layer 20): terminal code, company name and activity of each."""
    data = query(PLOTS_LAYER, "TERMINALCODE,ACTIVITEIT,GEBRUIK,BEDRIJFSNAAM")
    features = [{"type": "Feature", "geometry": f["geometry"],
                 "properties": {"terminal_code": f["properties"].get("TERMINALCODE"),
                                "activity": f["properties"].get("ACTIVITEIT"), "use": f["properties"].get("GEBRUIK"),
                                "company": f["properties"].get("BEDRIJFSNAAM")}}
                for f in data["features"] if f.get("geometry")]
    PLOTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    PLOTS_OUT.write_text(json.dumps({"type": "FeatureCollection", "name": "havenmeester_bedrijven", "source": PLOTS_LAYER,
                                     "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "features": features}, ensure_ascii=False), encoding="utf-8")
    log.info("%d company plots -> %s", len(features), PLOTS_OUT)


def fetch_tank_barge_berths():
    """The stretches where inland tank barges may lie (LIGPL layer 7), with their blue-cone class."""
    data = query(TANK_LAYER)
    features = []
    for f in data["features"]:
        if not f.get("geometry"):
            continue
        code = int(f["properties"].get("LIGPLAATS_TANKSCHEPEN") or 0)
        features.append({"type": "Feature", "geometry": f["geometry"],
                         "properties": {"id": f["properties"].get("OBJECTID"), "class": code,
                                        "meaning": TANK_CLASSES.get(code)}})
    TANK_OUT.write_text(json.dumps({"type": "FeatureCollection", "name": "tankvaart", "source": TANK_LAYER,
                                    "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "features": features}, ensure_ascii=False), encoding="utf-8")
    log.info("%d tank-barge stretches -> %s", len(features), TANK_OUT)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plots-only", action="store_true", help="only download the company plots")
    args = parser.parse_args()
    fetch_plots()
    fetch_tank_barge_berths()
    if args.plots_only:
        return
    data = query(LAYER)
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
