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

# site_id = <basin>-<band letter><nn>, numbered by score (desc) within
# basin+band, e.g. ST-H01 = best HIGH site in the Stillaguamish. District and
# HUC10 drainage ride along as columns for sorting/pattern analysis — the WGS
# district polygons tile most of the corridor, so they'd be noise inside the id.
BASINS = {"17110006": ("SA", "Sauk"), "17110008": ("ST", "Stillaguamish"),
          "17110009": ("SK", "Skykomish"), "17110011": ("SN", "Snohomish-Pilchuck"),
          "17110010": ("SQ", "Snoqualmie")}

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


def load_scored_segments(run_id=None):
    """Latest (or named) score run joined to segments + access, with the
    eligibility mask used by both the pre-committed draw and --explore."""
    with sqlite3.connect(GPKG) as db:
        runs = pd.read_sql("select run_id from score_runs order by ts", db)
        run_id = run_id or runs.iloc[-1]["run_id"]
        sc = pd.read_sql("select * from scores where run_id = ?", db, params=(run_id,))
    seg = gpd.read_file(GPKG, layer="stream_segments")
    access = pd.read_parquet(ROOT / "data" / "interim" / "segment_access.parquet")
    df = seg.merge(sc, on="segment_id").merge(access, left_on="segment_id", right_index=True)
    pannable = (df["StreamOrde"] >= 3) | (df["TotDASqKm"] >= 5)
    eligible = pannable & (df["access_status"] == "likely_open") & (~df["claim_conflict"])
    return run_id, df, pannable, eligible


def explore(codes, n_want, run_id=None) -> int:
    """--explore mode: append an EXPL band of the top within-basin segments
    for basins the percentile bands skipped (e.g. SN, whose best scores fall
    in the unsampled 70th-90th pct gap). Site ids <basin>-X<nn>. The existing
    pre-committed plan is left byte-identical; new rows append after it."""
    run_id, df, pannable, eligible = load_scored_segments(run_id)
    # Recon relaxation: unknown_check_parcel enters the pool (verifying the
    # parcel IS the recon step, e.g. public bridge crossings on private
    # valleys). Legal closures (dnr_closed_no_contract, closed, restricted,
    # permission_needed) stay out, as does anything claim-flagged.
    eligible = pannable & df["access_status"].isin(
        ["likely_open", "unknown_check_parcel"]) & (~df["claim_conflict"])
    print(f"exploration draw from run {run_id}: basins {', '.join(codes)}")
    occ_names = gpd.read_file(GPKG, layer="occurrences").set_index("occ_id")["name"]
    plan = pd.read_csv(FIELD / "sample_sites.csv")
    if (plan["band"] == "EXPL").any():
        plan = plan[plan["band"] != "EXPL"].copy()
        print("  (replacing previous EXPL rows; pre-committed bands untouched)")
    taken = gpd.GeoSeries(gpd.points_from_xy(plan["lon"], plan["lat"]),
                          crs="EPSG:4326").to_crs(df.crs)

    df["huc8"] = df["ReachCode"].astype(str).str[:8]
    code2huc = {v[0]: k for k, v in BASINS.items()}
    picks = []
    for code in codes:
        huc = code2huc[code]
        pool = (df[eligible & (df["huc8"] == huc)]
                .sort_values("total_score", ascending=False))
        chosen = []
        for _, row in pool.iterrows():
            pt = row.geometry.interpolate(0.5, normalized=True)
            if all(pt.distance(p) >= MIN_SPACING_M for p in taken) and \
               all(pt.distance(c["site_pt"]) >= MIN_SPACING_M for c in chosen):
                row = row.copy()
                row["site_pt"] = pt
                chosen.append(row)
            if len(chosen) == n_want:
                break
        print(f"  {code}: {len(chosen)}/{n_want} sites "
              f"(basin-local scores {chosen[-1]['total_score']:.0f}-"
              f"{chosen[0]['total_score']:.0f})" if chosen else f"  {code}: none eligible")
        for i, row in enumerate(chosen, 1):
            picks.append((code, f"{code}-X{i:02d}", row))

    if not picks:
        print("no exploration sites drawn")
        return 1
    sites = gpd.GeoDataFrame(
        [{
            "site_id": sid, "band": "EXPL",
            "segment_id": r["segment_id"], "ReachCode": str(r["ReachCode"]),
            "river": r["GNIS_Name"] if isinstance(r["GNIS_Name"], str) else "unnamed",
            "score": round(r["total_score"], 1),
            "source_score": round(r["source_score"], 1),
            "transport_score": round(r["transport_score"], 1),
            "nearest_gold_source": occ_names.get(r["top_occ_id"], ""),
            "dist_km": round(r["top_occ_dist_km"], 1) if pd.notna(r["top_occ_dist_km"]) else None,
            "order": int(r["StreamOrde"]),
            "slope_pct": round(r["slope_pct"], 2) if pd.notna(r["slope_pct"]) else None,
            "below_dam": bool(r["below_dam"]),
            "access_note": ("likely_open" if r["access_status"] == "likely_open"
                            else "UNKNOWN - check county parcel before entry"),
            "geometry": r["site_pt"],
        } for code, sid, r in picks], crs=df.crs).to_crs("EPSG:4326")
    sites["lat"] = sites.geometry.y.round(6)
    sites["lon"] = sites.geometry.x.round(6)
    huc8 = sites["ReachCode"].str[:8]
    sites["basin_code"] = huc8.map({k: v[0] for k, v in BASINS.items()})
    sites["basin"] = huc8.map({k: v[1] for k, v in BASINS.items()})
    pts = sites[["geometry"]].to_crs(df.crs)
    dist = gpd.read_file(GPKG, layer="mining_districts")
    j = gpd.sjoin(pts, dist[["DistrictNm", "geometry"]], how="left", predicate="within")
    sites["district"] = j.groupby(level=0)["DistrictNm"].first().fillna("")
    h10 = gpd.read_file(GPKG, layer="wbdhu10")
    j = gpd.sjoin(pts, h10[["HUC10", "Name", "geometry"]], how="left", predicate="within")
    sites["huc10"] = j.groupby(level=0)["HUC10"].first().fillna("")
    sites["huc10_name"] = j.groupby(level=0)["Name"].first().fillna("")
    sites = sites.drop(columns="ReachCode")

    print("fetching drive times from home (OSRM)...")
    sites["drive_min"], sites["road_snap_km"] = drive_times(sites)
    sites["window"] = "verify G&F pamphlet - basin not in plan tables yet"
    sites["legal_now"] = ""
    sites["access_cost"] = (sites["drive_min"] + 15 * sites["road_snap_km"]).round(1)
    sites = sites.sort_values(["drive_min", "site_id"],
                              na_position="last").reset_index(drop=True)

    cols = [c for c in plan.columns if c != "access_note"] + ["access_note"]
    out = pd.concat([plan, sites.drop(columns="geometry")],
                    ignore_index=True).reindex(columns=cols)
    out.to_csv(FIELD / "sample_sites.csv", index=False)
    write_gpx(out, run_id)
    try:  # keep the map layer in step (gpkg is local-only)
        old = gpd.read_file(GPKG, layer="sample_sites")
        old = old[old["band"] != "EXPL"] if "band" in old else old
        gpd.GeoDataFrame(pd.concat([old, sites.to_crs(old.crs)], ignore_index=True),
                         crs=old.crs).to_file(GPKG, layer="sample_sites", driver="GPKG")
    except Exception as e:
        print(f"  WARNING: gpkg sample_sites layer not updated ({e})")
    print(f"appended {len(sites)} EXPL sites -> field/sample_sites.csv, .gpx")
    print(sites[["site_id", "river", "score", "drive_min", "road_snap_km"]].to_string())
    return 0


def write_gpx(sites, run_id):
    wpts = []
    for _, s in sites.iterrows():
        name = f"{s['site_id']} {s['score']:.0f} {str(s['river'])[:20]}"
        drive = (f"{s['drive_min']:.0f} min drive + {s['road_snap_km']} km off-road"
                 if pd.notna(s["drive_min"]) else "drive time n/a")
        desc = (f"band {s['band']} | score {s['score']}/70 (src {s['source_score']}, "
                f"tr {s['transport_score']}) | {drive} | order {s['order']} | "
                f"nearest source: {s['nearest_gold_source'] if isinstance(s['nearest_gold_source'], str) else '-'} {s['dist_km'] if pd.notna(s['dist_km']) else ''} km"
                + (f" | {s['district']} district" if isinstance(s["district"], str) and s["district"] else "")
                + (" | BELOW DAM" if s["below_dam"] else ""))
        sym = {"HIGH": "Flag, Red", "MID": "Flag, Blue",
               "EXPL": "Pin, Yellow"}.get(s["band"], "Flag, Green")
        wpts.append(
            f'  <wpt lat="{s.lat}" lon="{s.lon}">\n'
            f'    <name>{escape(name)}</name>\n'
            f'    <desc>{escape(desc)}</desc>\n'
            f'    <sym>{sym}</sym>\n'
            f'  </wpt>')
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="prospecting-v02" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'  <metadata><name>Sky-Stilly-Sauk sampling plan ({run_id})</name></metadata>\n'
           + "\n".join(wpts) + "\n</gpx>\n")
    (FIELD / "sample_sites.gpx").write_text(gpx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--explore", default=None, metavar="CODES",
                    help="comma-separated basin codes (e.g. SN): append an EXPL "
                         "band of top within-basin sites instead of redrawing "
                         "the pre-committed plan")
    ap.add_argument("--explore-n", type=int, default=8,
                    help="sites per basin in --explore mode (default 8)")
    args = ap.parse_args()
    if args.explore:
        return explore([c.strip().upper() for c in args.explore.split(",")],
                       args.explore_n, args.run_id)

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
            "ReachCode": str(r["ReachCode"]),
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

    # ---- basin / district / drainage attribution + basin-coded ids -------
    huc8 = sites["ReachCode"].str[:8]
    sites["basin_code"] = huc8.map({k: v[0] for k, v in BASINS.items()})
    sites["basin"] = huc8.map({k: v[1] for k, v in BASINS.items()})
    pts = sites[["geometry"]].to_crs(seg.crs)
    dist = gpd.read_file(GPKG, layer="mining_districts")
    j = gpd.sjoin(pts, dist[["DistrictNm", "geometry"]], how="left", predicate="within")
    sites["district"] = j.groupby(level=0)["DistrictNm"].first().fillna("")
    h10 = gpd.read_file(GPKG, layer="wbdhu10")
    j = gpd.sjoin(pts, h10[["HUC10", "Name", "geometry"]], how="left", predicate="within")
    sites["huc10"] = j.groupby(level=0)["HUC10"].first().fillna("")
    sites["huc10_name"] = j.groupby(level=0)["Name"].first().fillna("")
    sites = sites.sort_values(["basin_code", "band", "score"],
                              ascending=[True, True, False])
    seq = sites.groupby(["basin_code", "band"]).cumcount() + 1
    sites["site_id"] = (sites["basin_code"] + "-" + sites["band"].str[0]
                        + seq.map("{:02d}".format))
    sites = sites.drop(columns="ReachCode")

    print("fetching drive times from home (OSRM)...")
    sites["drive_min"], sites["road_snap_km"] = drive_times(sites)
    sites = sites.sort_values(["drive_min", "band", "site_id"],
                              na_position="last").reset_index(drop=True)

    FIELD.mkdir(exist_ok=True)
    sites.drop(columns="geometry").to_csv(FIELD / "sample_sites.csv", index=False)
    sites.to_file(GPKG, layer="sample_sites", driver="GPKG")  # for the map (07)

    wpts = []
    for _, s in sites.iterrows():
        name = f"{s['site_id']} {s['score']:.0f} {s['river'][:20]}"
        drive = (f"{s['drive_min']:.0f} min drive + {s['road_snap_km']} km off-road"
                 if pd.notna(s["drive_min"]) else "drive time n/a")
        desc = (f"band {s['band']} | score {s['score']}/70 (src {s['source_score']}, "
                f"tr {s['transport_score']}) | {drive} | order {s['order']} | "
                f"nearest source: {s['nearest_gold_source'] or '-'} {s['dist_km'] or ''} km"
                + (f" | {s['district']} district" if s["district"] else "")
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
