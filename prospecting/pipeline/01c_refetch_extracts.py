"""Stage 01c — refetch the overlay service extracts for the current bbox.

The geology / ownership / claims layers have no bulk download wired into the
pipeline; they are bbox extracts of official ArcGIS services (endpoints below,
provenance in docs/01_data_inventory.md). Re-run this after changing
common.BBOX_4326. Uses paginated GeoJSON queries (resultOffset), which every
one of these servers supports.
"""
import json
import sys
import urllib.parse
import urllib.request

from common import BBOX_4326, RAW, ensure_dirs

DNR1 = "https://gis.dnr.wa.gov/site1/rest/services"
DNR3 = "https://gis.dnr.wa.gov/site3/rest/services"
BLM = "https://gis.blm.gov/nlsdb/rest/services/HUB"

LAYERS = {
    "wgs_geology_100k.geojson":
        f"{DNR1}/Public_Geology/100K_Surface_Geology_WA_GeMS/MapServer/11",
    "ndmpl_ownership.geojson":
        f"{DNR3}/Public_Boundaries/WADNR_PUBLIC_Major_Public_Lands_NonDNR/MapServer/1",
    "dnr_managed_lands.geojson":
        f"{DNR3}/Public_Boundaries/WADNR_PUBLIC_Managed_Lands/MapServer/1",
    "blm_claims_active.geojson":
        f"{BLM}/BLM_Natl_MLRS_Mining_Claims_Not_Closed/FeatureServer/0",
    "blm_claims_closed.geojson":
        f"{BLM}/BLM_Natl_MLRS_Mining_Claims_Closed/FeatureServer/0",
}

PAGE = 1000


def fetch_layer(url: str) -> list:
    feats, offset = [], 0
    while True:
        params = urllib.parse.urlencode({
            "geometry": ",".join(map(str, BBOX_4326)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*", "f": "geojson",
            "resultOffset": offset, "resultRecordCount": PAGE,
        })
        # gis.blm.gov 403s the default urllib User-Agent
        req = urllib.request.Request(f"{url}/query?{params}",
                                     headers={"User-Agent": "Mozilla/5.0 (prospecting-pipeline)"})
        with urllib.request.urlopen(req, timeout=120) as r:
            page = json.load(r)
        if "features" not in page:
            raise RuntimeError(f"bad response from {url}: {str(page)[:200]}")
        feats.extend(page["features"])
        if not page.get("properties", {}).get("exceededTransferLimit") \
                and not page.get("exceededTransferLimit"):
            break
        offset += PAGE
    return feats


def main() -> int:
    ensure_dirs()
    for name, url in LAYERS.items():
        print(f"  [fetch] {name} <- {url}")
        feats = fetch_layer(url)
        with open(RAW / name, "w") as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f)
        print(f"  [done]  {name}: {len(feats)} features")
    return 0


if __name__ == "__main__":
    sys.exit(main())
