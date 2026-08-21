"""Stage 07 — interactive HTML map (self-contained folium export).

Renders the latest (or named) score run: streams colored by prospectivity,
occurrences, claims, ownership/access, districts, study boundary. Open
map/index.html in any browser; works offline except basemap tiles.
"""
import argparse
import sqlite3
import sys

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from branca.colormap import LinearColormap

from common import GPKG, ROOT

OUT = ROOT / "map"
V02_MAX = 70.0  # trap score (30 pts) reserved for Phase 2


def load_run(run_id=None):
    with sqlite3.connect(GPKG) as db:
        runs = pd.read_sql("select run_id, ts from score_runs order by ts", db)
        if run_id is None:
            run_id = runs.iloc[-1]["run_id"]
        sc = pd.read_sql("select * from scores where run_id = ?", db, params=(run_id,))
    return run_id, sc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--near", default=None, metavar="LAT,LON,KM",
                    help="clip to a radius around a point, e.g. 47.82,-121.55,20 "
                         "- small fast file for one day's ground")
    ap.add_argument("--out", default=None, help="output filename under map/")
    ap.add_argument("--lite", action="store_true",
                    help="smaller export for phone/artifact use (writes map/lite.html): "
                         "keeps only order>=4 or score>=15 segments, heavier simplification")
    args = ap.parse_args()

    run_id, sc = load_run(args.run_id)
    print(f"rendering run {run_id}")

    seg = gpd.read_file(GPKG, layer="stream_segments")
    occ = gpd.read_file(GPKG, layer="occurrences")
    claims = gpd.read_file(GPKG, layer="claims_active")
    dist = gpd.read_file(GPKG, layer="mining_districts")
    access = pd.read_parquet(ROOT / "data" / "interim" / "segment_access.parquet")

    seg = seg.merge(sc, on="segment_id").merge(
        access, left_on="segment_id", right_index=True)
    occ_names = occ.set_index("occ_id")["name"]

    # trim clutter: drop order-1/2 segments with negligible score
    if args.lite:
        seg = seg[(seg["StreamOrde"] >= 4) | (seg["total_score"] >= 15)].copy()
        seg["geometry"] = seg.geometry.simplify(40)
    else:
        seg = seg[(seg["StreamOrde"] >= 3) | (seg["total_score"] >= 8)].copy()
        seg["geometry"] = seg.geometry.simplify(15)
    if args.near:
        import shapely.geometry as _sg
        la, lo, km = (float(v) for v in args.near.split(","))
        clip = (gpd.GeoSeries([_sg.Point(lo, la)], crs="EPSG:4326")
                .to_crs(seg.crs).buffer(km * 1000).iloc[0])
        seg = seg[seg.geometry.intersects(clip)]
        occ = occ[occ.geometry.intersects(clip)]
        claims = claims[claims.geometry.intersects(clip)]
        dist = dist[dist.geometry.intersects(clip)]
        print(f"clipped to {km:.0f} km around {la},{lo}")
    print(f"{len(seg)} segments on map")

    import shapely
    def slim(g, nd=5):
        g = g.to_crs("EPSG:4326")
        g["geometry"] = shapely.set_precision(g.geometry, 10 ** -nd)
        return g

    seg4326 = slim(seg)
    occ4326 = occ.to_crs("EPSG:4326")
    claims4326 = slim(claims)
    dist4326 = slim(dist)

    ctr = ([float(args.near.split(",")[0]), float(args.near.split(",")[1])]
           if args.near else [47.90, -121.70])
    zoom = 12 if args.near else 9
    m = folium.Map(location=ctr, zoom_start=zoom, tiles=None, prefer_canvas=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        attr="USGS The National Map", name="USGS Topo").add_to(m)

    cmap = LinearColormap(["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"],
                          vmin=0, vmax=V02_MAX, caption=f"Prospectivity score (V0.3, max {int(V02_MAX)})")
    cmap.add_to(m)

    # ---- streams (single GeoJson layer; properties drive style + popup) --
    sj = seg4326.copy()
    sj["river"] = sj["GNIS_Name"].fillna("unnamed stream")
    sj["score_txt"] = sj["total_score"].round(0).astype(int).astype(str) + f"/{int(V02_MAX)} (V0.3 — trap score where LiDAR exists)"
    sj["parts"] = ("source " + sj["source_score"].round(0).astype(int).astype(str) + "/40 · transport "
                   + sj["transport_score"].round(0).astype(int).astype(str) + "/20 · confidence "
                   + sj["confidence_score"].round(0).astype(int).astype(str) + "/10")
    sj["nearest_src"] = sj["top_occ_id"].map(occ_names).fillna("—")
    sj["src_dist"] = sj["top_occ_dist_km"].map(lambda v: f"{v:.1f} km" if pd.notna(v) else "—")
    sj["claim"] = np.where(sj["claim_conflict"], "YES — section-level, verify serial in MLRS", "no")
    sj["dam_note"] = np.where(sj["below_dam"], "below Culmback Dam (sediment-starved)", "")
    sj["hydro"] = (sj["slope_pct"].round(2).astype(str) + "% slope · "
                   + sj["TotDASqKm"].round(0).astype(int).astype(str) + " km² drainage · order "
                   + sj["StreamOrde"].astype(int).astype(str))
    sj["color"] = sj["total_score"].map(cmap)
    sj["weight"] = 1.5 + 0.9 * (sj["StreamOrde"] - 2) + np.where(sj["total_score"] > 40, 1.5, 0)
    keep = ["river", "score_txt", "parts", "nearest_src", "src_dist", "n_upstream_gold",
            "claim", "access_status", "dam_note", "hydro", "color", "weight", "geometry"]
    fg_streams = folium.GeoJson(
        sj[keep].to_json(),
        name="Stream prospectivity",
        style_function=lambda f: {"color": f["properties"]["color"],
                                  "weight": f["properties"]["weight"], "opacity": 0.9},
        popup=folium.GeoJsonPopup(
            fields=["river", "score_txt", "parts", "nearest_src", "src_dist",
                    "n_upstream_gold", "claim", "access_status", "dam_note", "hydro"],
            aliases=["Stream", "Prospectivity", "Components", "Nearest upstream gold source",
                     "Distance downstream", "Upstream gold records", "Claim conflict",
                     "Access", "", "Hydrology"],
            max_width=340),
    )
    fg_streams.add_to(m)

    # ---- access overlays: one layer per legal class -----------------------
    ACCESS_STYLES = {
        "closed": ("Access: CLOSED (state parks / water-supply lands)",
                   {"color": "#000000", "weight": 2.0, "opacity": 0.85, "dashArray": "1 4"}),
        "dnr_closed_no_contract": ("Access: DNR trust land (closed w/o placer contract)",
                   {"color": "#5c3c92", "weight": 1.6, "opacity": 0.8, "dashArray": "1 5"}),
        "restricted": ("Access: Wilderness (withdrawn — no-go)",
                   {"color": "#555555", "weight": 1.2, "opacity": 0.7, "dashArray": "2 6"}),
        "permission_needed": ("Access: permission needed (WDFW/county/city)",
                   {"color": "#b8860b", "weight": 1.4, "opacity": 0.8, "dashArray": "4 4"}),
        "unknown_check_parcel": ("Access: unknown — likely PRIVATE, check parcels",
                   {"color": "#c04000", "weight": 1.2, "opacity": 0.6, "dashArray": "6 3"}),
    }
    for status, (label, style) in ACCESS_STYLES.items():
        sub = seg4326.loc[seg4326["access_status"] == status, ["geometry"]]
        if len(sub):
            folium.GeoJson(sub.to_json(), name=label, show=(status != "unknown_check_parcel"),
                           style_function=lambda f, s=style: s).add_to(m)

    # ---- occurrences -----------------------------------------------------
    fg_occ = folium.FeatureGroup(name="Gold occurrences (fused)", show=True)
    for _, o in occ4326.iterrows():
        color = {"placer": "#e6a817", "lode": "#7a4a12", "unknown": "#777777"}[o["deposit_class"]]
        marker = folium.CircleMarker(
            [o.geometry.y, o.geometry.x],
            radius=7 if o["producer"] else 4,
            color=color, fill=True, fill_opacity=0.85, weight=1,
        )
        marker.add_child(folium.Popup(
            f"<b>{o['name'] or 'unnamed'}</b><br>"
            f"class: {o['deposit_class']} | producer: {'yes' if o['producer'] else 'no'}<br>"
            f"records fused: {o['n_records']} ({o['n_sources']} source db)<br>"
            f"commodities: {o['commodities'][:60]}<br>"
            f"workings within 300 m: {o['n_workings_300m']}<br>"
            f"ids: {o['source_ids'][:80]}", max_width=300))
        marker.add_to(fg_occ)
    fg_occ.add_to(m)

    # ---- claims ----------------------------------------------------------
    cj = claims4326.copy()
    cj["note"] = "Geometry is the PLSS section, NOT the claim boundary"
    folium.GeoJson(
        cj[["CSE_NAME", "claim_kind", "CSE_DISP", "CSE_NR", "RCRD_ACRS", "note", "geometry"]].to_json(),
        name="Active mining claims (section-level)",
        style_function=lambda f: {"color": "#cc0000", "weight": 1,
                                  "fillColor": "#cc0000", "fillOpacity": 0.12},
        popup=folium.GeoJsonPopup(
            fields=["CSE_NAME", "claim_kind", "CSE_DISP", "CSE_NR", "RCRD_ACRS", "note"],
            aliases=["Claim", "Type", "Status", "MLRS serial", "Record acres", ""],
            max_width=280),
    ).add_to(m)

    # ---- districts -------------------------------------------------------
    fg_dist = folium.FeatureGroup(name="Historical mining districts", show=False)
    for _, dd in dist4326.iterrows():
        gj = folium.GeoJson(dd.geometry.__geo_interface__,
                            style_function=lambda _: {"color": "#6a3d9a", "weight": 2,
                                                      "fill": False, "dashArray": "8 4"})
        gj.add_child(folium.Tooltip(dd["DistrictNm"] + " district"))
        gj.add_to(fg_dist)
    fg_dist.add_to(m)

    # ---- proposed sample sites (stage 08, if drawn) ----------------------
    try:
        ss = gpd.read_file(GPKG, layer="sample_sites").to_crs("EPSG:4326")
    except Exception:
        ss = None
    if ss is not None:
        band_fill = {"HIGH": "#d7191c", "MID": "#2c7bb6", "LOW": "#33a02c",
                     "EXPL": "#e6a817"}  # recon band (08 --explore)
        fg_sites = folium.FeatureGroup(name=f"Proposed sample sites ({len(ss)})", show=True)
        for _, s in ss.iterrows():
            mk = folium.CircleMarker(
                [s.geometry.y, s.geometry.x], radius=6,
                color="#000000", weight=1.5, fill=True,
                fill_color=band_fill[s["band"]], fill_opacity=0.95)
            drive = (f"{s['drive_min']:.0f} min drive + {s['road_snap_km']} km off-road"
                     if pd.notna(s["drive_min"]) else "drive time n/a")
            mk.add_child(folium.Tooltip(s["site_id"], permanent=True,
                                        direction="right", className="site-label"))
            mk.add_child(folium.Popup(
                f"<b>{s['site_id']}</b> — {s['band']} band<br>"
                f"{s['river']} ({s['basin']} basin, HUC10 {s['huc10_name'] or '?'})<br>"
                f"score {s['score']}/70 | {drive}<br>"
                f"nearest source: {s['nearest_gold_source'] or '—'}"
                f"{f' ({s.dist_km} km)' if pd.notna(s['dist_km']) else ''}<br>"
                + (f"district: {s['district']}<br>" if s["district"] else "")
                + f"{s['lat']}, {s['lon']}", max_width=300))
            mk.add_to(fg_sites)
        fg_sites.add_to(m)
        m.get_root().html.add_child(folium.Element(
            "<style>.site-label{font:10px/1.1 sans-serif;padding:1px 4px;"
            "background:rgba(255,255,255,.88);border:1px solid #999;"
            "box-shadow:none;}</style>"))

    # ---- logged field samples (real results) -----------------------------
    fs_csv = ROOT / "field" / "field_samples_log.csv"
    if fs_csv.exists():
        fs = pd.read_csv(fs_csv)
        fs = fs[fs["lat"].notna() & fs["lon"].notna()]
        if len(fs):
            fg_fs = folium.FeatureGroup(name=f"MY field samples ({len(fs)})", show=True)
            for _, r in fs.iterrows():
                gold = str(r.get("gold_character", "")).lower()
                found = gold not in ("", "nan", "none")
                folium.Marker(
                    [r["lat"], r["lon"]],
                    icon=folium.Icon(color="green" if found else "gray",
                                     icon="star" if found else "remove"),
                    tooltip=f"{r['site_id']}: {'GOLD' if found else 'no gold'}",
                    popup=folium.Popup(
                        f"<b>{r['site_id']}</b> — {r.get('date','')}<br>"
                        f"result: <b>{r.get('gold_character') or 'none'}</b><br>"
                        f"pans: {r.get('pans')} | colors: {r.get('colors')}<br>"
                        f"{str(r.get('notes',''))[:200]}", max_width=320),
                ).add_to(fg_fs)
            fg_fs.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    def dash(color, pattern):
        return (f'<svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" '
                f'stroke="{color}" stroke-width="2.5" stroke-dasharray="{pattern}"/></svg>')

    note = f"""
    <style>
      #legend-toggle {{
        position: fixed; bottom: 12px; left: 12px; z-index: 10000;
        background: rgba(255,255,255,0.95); border: 1px solid #888;
        border-radius: 6px; padding: 7px 11px; font: 600 13px sans-serif;
        cursor: pointer; box-shadow: 0 1px 4px rgba(0,0,0,0.3);
      }}
      #legend-box.hidden {{ display: none; }}
      /* phones: legend starts hidden, layer panel and colour bar shrink */
      @media (max-width: 760px) {{
        #legend-box {{
          bottom: 54px !important; left: 8px !important; right: 8px !important;
          max-width: none !important; max-height: 45vh; overflow-y: auto;
          font-size: 11px !important;
        }}
        .leaflet-control-layers {{ max-height: 55vh; overflow-y: auto; font-size: 12px; }}
        .leaflet-control-colorbar, .legend.leaflet-control {{ transform: scale(0.7);
          transform-origin: top right; }}
      }}
    </style>
    <button id="legend-toggle" onclick="var b=document.getElementById('legend-box');
      b.classList.toggle('hidden');
      this.textContent = b.classList.contains('hidden') ? 'Legend \u25B2' : 'Legend \u25BC';">Legend &#9660;</button>
    <div id="legend-box" style="position: fixed; bottom: 12px; left: 12px; z-index: 9999;
                background: rgba(255,255,255,0.93); padding: 8px 12px; border-radius: 6px;
                font: 12px/1.45 sans-serif; max-width: 400px; box-shadow: 0 1px 4px rgba(0,0,0,0.3);">
      <b>Skykomish–Stillaguamish–Sauk–Snoqualmie prospectivity — V0.3</b> (run {run_id})<br>
      Relative rank, <b>not</b> a probability of finding gold. Scores max at 70/100
      until terrain-trap scoring (Phase 2). Verify claims in BLM MLRS and current
      WDFW Gold &amp; Fish rules before digging. In-water work windows apply
      (work windows differ per river — Skykomish mainstem/SF close after Aug 15).<hr style="margin:6px 0">
      <b>Access overlays</b> (drawn over the score color):<br>
      {dash('#000000','1 4')} closed — state parks &amp; water-supply lands<br>
      {dash('#5c3c92','1 5')} DNR trust land — closed without placer contract<br>
      {dash('#555555','2 6')} wilderness — withdrawn, no-go<br>
      {dash('#b8860b','4 4')} permission needed — WDFW / county / city<br>
      {dash('#c04000','6 3')} unknown — likely private, check county parcels<br>
      no overlay = likely open (non-designated National Forest, casual use)<br>
      <span style="color:#cc0000">■</span> red section = active mining claim (section-level)
      &nbsp;·&nbsp; <span style="color:#e6a817">●</span> placer &nbsp;<span style="color:#7a4a12">●</span> lode
      (large = past producer)<br>
      Labeled dots = proposed sample sites (basin-band id, e.g. ST-H01):
      <span style="color:#d7191c">●</span> HIGH &nbsp;<span style="color:#2c7bb6">●</span> MID
      &nbsp;<span style="color:#33a02c">●</span> LOW
    </div>
    <script>
      // start collapsed on phone-sized screens so the map is visible
      if (window.matchMedia("(max-width: 760px)").matches) {{
        document.getElementById("legend-box").classList.add("hidden");
        document.getElementById("legend-toggle").textContent = "Legend \u25B2";
      }}
    </script>"""
    m.get_root().html.add_child(folium.Element(note))

    OUT.mkdir(exist_ok=True)
    out = OUT / (args.out or ("lite.html" if args.lite else "index.html"))
    m.save(str(out))
    from webassets import inline_assets
    inline_assets(out)
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
