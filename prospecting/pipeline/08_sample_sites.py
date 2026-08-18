"""Stage 08 — pre-committed field sampling plan.

Draws a stratified set of candidate sample sites from the latest score run:
  HIGH band = top decile, MID = 40-70th pct, LOW = 10-40th pct
Filters: access likely_open, no claim conflict, real streams only
(order >= 3 or drainage >= 5 km2), >= 1 km spacing within a band.

Outputs: field/sample_sites.csv, field/sample_sites.gpx,
         field/field_samples_log.csv (empty log matching the schema).
The draw is seeded — rerunning reproduces the same list unless the score
run or filters change. Sites are a PRE-COMMITTED protocol: sample them as
drawn; record extra opportunistic sites separately in the log.

Output rows are ordered by drive time from HOME (OSRM demo server, car
profile). drive_min is to the nearest OSM-mapped road; road_snap_km says how
far the site sits from that road (i.e., the hike/bushwhack remainder).
"""
import argparse
import json
import sqlite3
import sys
import urllib.request
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import pandas as pd

from common import GPKG, ROOT

FIELD = ROOT / "field"
BANDS = {"HIGH": (0.90, 1.00, 15), "MID": (0.40, 0.70, 10), "LOW": (0.10, 0.40, 10)}
MIN_SPACING_M = 1000
SEED = 42

# 3113 122nd Pl SW, Everett WA 98204 (Census geocoder, 2026-08-18)
HOME = (-122.275171, 47.886925)  # lon, lat
OSRM = "https://router.project-osrm.org/table/v1/driving"


def drive_times(sites):
    """Minutes of driving from HOME to each site + road snap distance (km)."""
    mins = np.full(len(sites), np.nan)
    snap_km = np.full(len(sites), np.nan)
    chunk = 80  # demo server caps table requests at 100 coordinates
    for i0 in range(0, len(sites), chunk):
        part = sites.iloc[i0:i0 + chunk]
        coords = ";".join([f"{HOME[0]:.6f},{HOME[1]:.6f}"]
                          + [f"{s.lon},{s.lat}" for _, s in part.iterrows()])
        url = f"{OSRM}/{coords}?sources=0&annotations=duration"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            if d.get("code") != "Ok":
                raise RuntimeError(d.get("code"))
            durs = d["durations"][0][1:]
            snaps = d["destinations"][1:]
            for j, (dur, dest) in enumerate(zip(durs, snaps)):
                if dur is not None:
                    mins[i0 + j] = dur / 60
                snap_km[i0 + j] = dest.get("distance", np.nan) / 1000
        except Exception as e:
            print(f"  WARNING: OSRM request failed ({e}) — drive times missing "
                  f"for sites {i0}..{i0 + len(part) - 1}")
    return mins.round(0), snap_km.round(1)

LOG_COLUMNS = [
    "site_id", "date", "time", "lat", "lon", "gps_acc_m", "site_type",
    "pans", "material_l", "colors", "est_gold_mg", "largest_particle_mm",
    "gold_character", "black_sand_0_3", "bedrock_present", "sediment_desc",
    "water_level_note", "photos", "opportunistic", "notes",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    with sqlite3.connect(GPKG) as db:
        runs = pd.read_sql("select run_id from score_runs order by ts", db)
        run_id = args.run_id or runs.iloc[-1]["run_id"]
        sc = pd.read_sql("select * from scores where run_id = ?", db, params=(run_id,))
    print(f"drawing sites from run {run_id}")

    seg = gpd.read_file(GPKG, layer="stream_segments")
    access = pd.read_parquet(ROOT / "data" / "interim" / "segment_access.parquet")
    occ_names = gpd.read_file(GPKG, layer="occurrences").set_index("occ_id")["name"]

    df = seg.merge(sc, on="segment_id").merge(access, left_on="segment_id", right_index=True)
    pannable = (df["StreamOrde"] >= 3) | (df["TotDASqKm"] >= 5)
    eligible = df[pannable & (df["access_status"] == "likely_open") & (~df["claim_conflict"])].copy()
    print(f"{len(eligible)} eligible segments (open access, no claim flag, real streams)")

    # percentiles over ALL pannable segments so bands mean what the map shows
    ref = df.loc[pannable, "total_score"]
    rng = np.random.default_rng(SEED)
    picks = []
    for band, (p_lo, p_hi, n_want) in BANDS.items():
        lo, hi = ref.quantile(p_lo), ref.quantile(p_hi)
        pool = eligible[(eligible["total_score"] >= lo) & (eligible["total_score"] <= hi)].copy()
        # HIGH: prefer best first; MID/LOW: random order (seeded)
        pool = (pool.sort_values("total_score", ascending=False) if band == "HIGH"
                else pool.sample(frac=1, random_state=SEED))
        chosen = []
        for _, row in pool.iterrows():
            pt = row.geometry.interpolate(0.5, normalized=True)
            if all(pt.distance(c.geometry.interpolate(0.5, normalized=True)) >= MIN_SPACING_M
                   for c in chosen):
                row = row.copy()
                row["site_pt"] = pt
                chosen.append(row)
            if len(chosen) == n_want:
                break
        print(f"  {band}: {len(chosen)}/{n_want} sites (score {lo:.0f}-{hi:.0f})")
        for i, row in enumerate(chosen, 1):
            picks.append((band, f"{band[0]}{i:02d}", row))

    sites = gpd.GeoDataFrame(
        [{
            "site_id": sid,
            "band": band,
            "segment_id": r["segment_id"],
            "river": r["GNIS_Name"] if isinstance(r["GNIS_Name"], str) else "unnamed",
            "score": round(r["total_score"], 1),
            "source_score": round(r["source_score"], 1),
            "transport_score": round(r["transport_score"], 1),
            "nearest_gold_source": occ_names.get(r["top_occ_id"], ""),
            "dist_km": round(r["top_occ_dist_km"], 1) if pd.notna(r["top_occ_dist_km"]) else None,
            "order": int(r["StreamOrde"]),
            "slope_pct": round(r["slope_pct"], 2) if pd.notna(r["slope_pct"]) else None,
            "below_dam": bool(r["below_dam"]),
            "geometry": r["site_pt"],
        } for band, sid, r in picks], crs=seg.crs).to_crs("EPSG:4326")
    sites["lat"] = sites.geometry.y.round(6)
    sites["lon"] = sites.geometry.x.round(6)

    print("fetching drive times from home (OSRM)...")
    sites["drive_min"], sites["road_snap_km"] = drive_times(sites)
    sites = sites.sort_values(["drive_min", "band", "site_id"],
                              na_position="last").reset_index(drop=True)

    FIELD.mkdir(exist_ok=True)
    sites.drop(columns="geometry").to_csv(FIELD / "sample_sites.csv", index=False)

    wpts = []
    for _, s in sites.iterrows():
        name = f"{s['site_id']} {s['score']:.0f} {s['river'][:20]}"
        drive = (f"{s['drive_min']:.0f} min drive + {s['road_snap_km']} km off-road"
                 if pd.notna(s["drive_min"]) else "drive time n/a")
        desc = (f"band {s['band']} | score {s['score']}/70 (src {s['source_score']}, "
                f"tr {s['transport_score']}) | {drive} | order {s['order']} | "
                f"nearest source: {s['nearest_gold_source'] or '-'} {s['dist_km'] or ''} km"
                + (" | BELOW DAM" if s["below_dam"] else ""))
        wpts.append(
            f'  <wpt lat="{s.lat}" lon="{s.lon}">\n'
            f'    <name>{escape(name)}</name>\n'
            f'    <desc>{escape(desc)}</desc>\n'
            f'    <sym>{"Flag, Red" if s["band"]=="HIGH" else "Flag, Blue" if s["band"]=="MID" else "Flag, Green"}</sym>\n'
            f'  </wpt>')
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="prospecting-v02" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'  <metadata><name>Sky-Stilly-Sauk sampling plan ({run_id})</name></metadata>\n'
           + "\n".join(wpts) + "\n</gpx>\n")
    (FIELD / "sample_sites.gpx").write_text(gpx)

    log = FIELD / "field_samples_log.csv"
    if not log.exists() or len(pd.read_csv(log)) == 0:
        pd.DataFrame(columns=LOG_COLUMNS).to_csv(log, index=False)
    else:
        print("field_samples_log.csv has entries — left untouched")
    print(f"wrote {len(sites)} sites -> field/sample_sites.csv, .gpx; empty log created")
    print(sites.groupby("band")[["score"]].agg(["min", "max", "count"]).to_string())
    print("\nrivers in plan:", sites["river"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
