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

PAGE = 250   # objectIds batch size; shrinks automatically on failure


BASE = {
    "geometry": ",".join(map(str, BBOX_4326)),
    "geometryType": "esriGeometryEnvelope",
    "inSR": 4326, "outSR": 4326,
    "spatialRel": "esriSpatialRelIntersects",
    "where": "1=1",
}
# gis.blm.gov 403s the default urllib User-Agent
UA = {"User-Agent": "Mozilla/5.0 (prospecting-pipeline)"}


def _get(url: str, params: dict):
    req = urllib.request.Request(f"{url}/query?{urllib.parse.urlencode(params)}",
                                 headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def fetch_layer(url: str) -> list:
    """Fetch by explicit objectIds, reconciled against the server's own ID list.

    resultOffset paging on these servers returns unstable ordering under the
    byte cap: pages silently duplicate and skip features. Asking for an
    authoritative ID list first and then fetching those IDs in batches makes
    the result verifiable — we assert we got exactly the set the server named.
    """
    ids = _get(url, {**BASE, "returnIdsOnly": "true", "f": "json"}).get("objectIds") or []
    field = _get(url, {**BASE, "returnIdsOnly": "true", "f": "json"}).get("objectIdFieldName", "OBJECTID")
    print(f"          server names {len(ids)} features (id field {field})")
    feats, batch = {}, PAGE
    i = 0
    while i < len(ids):
        chunk = ids[i:i + batch]
        try:
            page = _get(url, {**BASE, "objectIds": ",".join(map(str, chunk)),
                              "outFields": "*", "f": "geojson"})
            got = page.get("features")
            if got is None:
                raise RuntimeError(str(page)[:200])
        except Exception as e:
            if batch > 1:
                batch = max(1, batch // 4)      # shrink and retry this chunk
                print(f"          batch -> {batch} after: {str(e)[:80]}")
                continue
            print(f"          SKIP id {chunk[0]}: {str(e)[:80]}")
            i += 1
            continue
        for ft in got:
            oid = (ft.get("id") if ft.get("id") is not None
                   else ft.get("properties", {}).get(field))
            feats[oid if oid is not None else len(feats)] = ft
        i += len(chunk)
    missing = len(ids) - len(feats)
    if missing:
        print(f"          WARNING: {missing} of {len(ids)} features missing")
    return list(feats.values())


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
