"""Stage 01 — fetch raw data.

Two classes of source:

1. USGS staged products on prd-tnm.s3.amazonaws.com — downloaded directly
   here (anonymous HTTP, reliable, resumable).

2. State/federal GIS services (WA DNR, BLM, mrdata.usgs.gov) — the canonical
   bulk downloads are listed in docs/01_data_inventory.md. In environments
   where those hosts are unreachable, bbox-limited GeoJSON extracts fetched
   from the official ArcGIS/WFS query endpoints are cached in data/raw/ and
   committed to the repo (they are small). This script only verifies their
   presence; refresh them from the service endpoints when network access
   allows (see EXTRACTS below for provenance).
"""
import sys
import urllib.request
from pathlib import Path

from common import RAW, ensure_dirs

S3 = "https://prd-tnm.s3.amazonaws.com/StagedProducts"

DOWNLOADS = {
    # streams + VAAs + WBD HUC layers for HU4 1711 (frozen snapshot, 2024-02-29)
    "NHDPLUS_H_1711_HU4_GDB.zip": f"{S3}/Hydrography/NHDPlusHR/VPU/Current/GDB/NHDPLUS_H_1711_HU4_GDB.zip",
    # 10 m DEM tile covering the whole corridor (hillshade only; optional)
    # "USGS_13_n48w122.tif": f"{S3}/Elevation/13/TIFF/current/n48w122/USGS_13_n48w122.tif",
}

# Service-extracted GeoJSON caches: filename -> source query endpoint (provenance)
EXTRACTS = {
    "wgs_gold_silver.geojson": "gis.dnr.wa.gov .../Mines_and_Minerals/MapServer/12/query (bbox extract)",
    "wgs_metallic.geojson": "gis.dnr.wa.gov .../Mines_and_Minerals/MapServer/13/query (bbox extract)",
    "wgs_mining_districts.geojson": "gis.dnr.wa.gov .../Mines_and_Minerals/MapServer/22/query (bbox extract)",
    "mrds.geojson": "mrdata.usgs.gov/services/wfs/mrds (bbox extract)",
    "usmin_points.geojson": "mrdata.usgs.gov/services/wfs/usmin (bbox extract)",
    "blm_claims_active.geojson": "gis.blm.gov .../BLM_Natl_MLRS_Mining_Claims_Not_Closed/FeatureServer/0/query (bbox extract)",
    "blm_claims_closed.geojson": "gis.blm.gov .../BLM_Natl_MLRS_Mining_Claims_Closed (bbox extract)",
    "wgs_geology_100k.geojson": "gis.dnr.wa.gov .../100K_Surface_Geology... (bbox extract)",
    "ndmpl_ownership.geojson": "gis.dnr.wa.gov site3 .../Major_Public_Lands_NonDNR (bbox extract)",
    "dnr_managed_lands.geojson": "gis.dnr.wa.gov site3 (DNR managed parcels, bbox extract)",
}


def fetch(name: str, url: str) -> None:
    dest = RAW / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [cached] {name} ({dest.stat().st_size/1e6:.0f} MB)")
        return
    print(f"  [fetch]  {name} <- {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    print(f"  [done]   {name} ({dest.stat().st_size/1e6:.0f} MB)")


def main() -> int:
    ensure_dirs()
    print("S3 downloads:")
    for name, url in DOWNLOADS.items():
        fetch(name, url)

    # unzip the NHDPlus GDB once (reading through /vsizip is far too slow)
    gdb = RAW / "NHDPLUS_H_1711_HU4_GDB.gdb"
    if not gdb.exists():
        import zipfile
        print("  unzipping NHDPlus GDB...")
        with zipfile.ZipFile(RAW / "NHDPLUS_H_1711_HU4_GDB.zip") as z:
            z.extractall(RAW)

    print("Service extracts (cached in repo):")
    missing = []
    for name, src in EXTRACTS.items():
        p = RAW / name
        if p.exists() and p.stat().st_size > 0:
            print(f"  [ok]      {name} ({p.stat().st_size/1e3:.0f} kB)")
        else:
            print(f"  [MISSING] {name}  — refetch from: {src}")
            missing.append(name)
    if missing:
        print(f"\n{len(missing)} extract(s) missing; see docs/01_data_inventory.md for endpoints.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
