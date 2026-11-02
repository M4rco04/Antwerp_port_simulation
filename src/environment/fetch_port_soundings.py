"""Download the Port of Antwerp-Bruges sounded bed levels (gepeilde diepte) as a GeoTIFF.

Source: webapps.portofantwerpbruges.com/arcgis/rest/services/extern/gepeilde_diepte/ImageServer
(public): the bed level from soundings in m TAW (negative below TAW), 1 m pixels, Belgian Lambert 72
(EPSG:31370), covering the Antwerp docks and the Zeeschelde. Exported here at RES_M resolution
(bilinear), no-data written as NODATA.

Usage:
    py src/environment/fetch_port_soundings.py
Writes data/charts/antwerp_port_soundings_taw.tif.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "charts" / "antwerp_port_soundings_taw.tif"
SERVICE = "https://webapps.portofantwerpbruges.com/arcgis/rest/services/extern/gepeilde_diepte/ImageServer"
RES_M = 5.0
NODATA = -9999.0

log = logging.getLogger("soundings")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with urllib.request.urlopen(f"{SERVICE}?f=json", timeout=60) as r:
        info = json.loads(r.read())
    e = info["extent"]
    width = int((e["xmax"] - e["xmin"]) / RES_M)
    height = int((e["ymax"] - e["ymin"]) / RES_M)
    params = {"bbox": f"{e['xmin']},{e['ymin']},{e['xmax']},{e['ymax']}", "bboxSR": 31370, "imageSR": 31370,
              "size": f"{width},{height}", "format": "tiff", "pixelType": "F32", "noData": NODATA,
              "interpolation": "RSP_BilinearInterpolation", "f": "image"}
    url = f"{SERVICE}/exportImage?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=600) as r:
        data = r.read()
    if data[:2] not in (b"II", b"MM"):
        raise RuntimeError(f"not a TIFF: {data[:300]!r}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    log.info("%d x %d pixels of %.0f m -> %s (%.1f MB)", width, height, RES_M, OUT, len(data) / 1e6)


if __name__ == "__main__":
    main()
