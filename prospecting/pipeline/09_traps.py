"""Stage 09 (Phase 2) — LiDAR-derived terrain traps per stream segment.

Fills the 30 reserved trap points of the score. Reads 1 m bare-earth DTM
tiles (data/raw/lidar/*.tif, USGS 3DEP WA_Western_North_2016) and derives,
for every segment inside coverage:

  grad_break   downstream DECREASE in channel slope (steep -> flat): where
               competence drops and coarse gold is dropped. The single most
               reliable placer trap signal available from a DEM.
  confinement  valley width 5 m above the channel, and its downstream
               change. Narrow = bedrock canyon (scour, crevices); a
               confinement RELEASE (narrow -> wide) is a deposition site.
  bend         planform curvature from the LiDAR-sampled long profile's
               geometry -> inside-bend point bars.
  bedrock      proxy: steep valley walls + mapped bedrock (non-Quaternary)
               geology. NOT a bedrock-exposure map; see docs.
  plunge       local slope spike (waterfall / chute) -> plunge pool below.

Outputs data/interim/segment_traps.parquet with raw metrics plus a
trap_score (0-30) built from weights.yaml components.trap.

LIMITS (read before trusting):
  * 1 m bare-earth interpolates water surfaces flat - there is NO channel
    bathymetry. Everything here is about the valley, not the streambed.
  * NHD flowline geometry is 1:24k and predates the LiDAR; on small creeks
    the mapped line can sit tens of metres off the real channel. Metrics
    are therefore reach-scale, not spot-scale.
  * 2016 vintage: post-2016 channel change is invisible.
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import uniform_filter1d

from common import CRS, GPKG, INTERIM, RAW, load_weights

LIDAR = RAW / "lidar"
STEP_M = 10.0        # along-channel sample spacing
XS_HALF_M = 300.0    # cross-section half-width searched for valley walls
XS_STEP_M = 4.0      # cross-section sample spacing
BANK_H_M = 5.0       # height above channel defining "valley width"


def sample_grid(arr, transform, xs, ys, nodata):
    """Nearest-neighbour sample of an in-memory array at map coords."""
    inv = ~transform
    cols, rows = inv * (xs, ys)
    cols = np.rint(cols).astype(int)
    rows = np.rint(rows).astype(int)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    out = np.full(xs.shape, np.nan, dtype="float32")
    v = arr[rows[ok], cols[ok]]
    v = np.where(v == nodata, np.nan, v)
    out[ok] = v
    return out


def densify(line, step=STEP_M):
    n = max(int(line.length // step) + 1, 2)
    d = np.linspace(0, line.length, n)
    pts = [line.interpolate(t) for t in d]
    return d, np.array([p.x for p in pts]), np.array([p.y for p in pts])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-drainage", type=float, default=200.0,
                    help="skip segments larger than this (km2); big rivers "
                         "need bathymetry this DEM does not have")
    args = ap.parse_args()

    tiles = sorted(LIDAR.glob("*.tif"))
    if not tiles:
        print(f"no LiDAR tiles in {LIDAR} — run the download first")
        return 1
    print(f"{len(tiles)} LiDAR tile(s)")

    seg = gpd.read_file(GPKG, layer="stream_segments").to_crs(CRS)
    rows = []

    for tif in tiles:
        with rasterio.open(tif) as src:
            b = src.bounds
            sub = seg.cx[b.left:b.right, b.bottom:b.top]
            sub = sub[sub["TotDASqKm"] <= args.max_drainage]
            if not len(sub):
                print(f"  {tif.name}: no segments"); continue
            # read once at 2 m (decimated) — plenty for valley form, 4x less RAM
            arr = src.read(1, out_shape=(src.height // 2, src.width // 2),
                           resampling=rasterio.enums.Resampling.average)
            tr = src.transform * src.transform.scale(2, 2)
            nod = src.nodata
            print(f"  {tif.name}: {len(sub)} segments, grid {arr.shape}")

            for _, s in sub.iterrows():
                line = s.geometry
                if line.length < 30:
                    continue
                d, xs, ys = densify(line)
                z = sample_grid(arr, tr, xs, ys, nod)
                if np.isnan(z).mean() > 0.4 or len(z) < 5:
                    continue
                # fill gaps, smooth the long profile (30 m window)
                idx = np.arange(len(z))
                good = ~np.isnan(z)
                if good.sum() < 4:
                    continue
                z = np.interp(idx, idx[good], z[good])
                w = max(3, int(30 / STEP_M) | 1)
                zs = uniform_filter1d(z, w)
                # slope % along channel (positive = downhill downstream)
                slope = -np.gradient(zs, d) * 100
                # gradient BREAK: downstream decrease in slope, normalised
                dslope = -np.gradient(uniform_filter1d(slope, w), d) * 1000
                grad_break = float(np.nanmax(dslope)) if len(dslope) else 0.0
                plunge = float(np.nanmax(slope)) if len(slope) else 0.0

                # ---- cross sections: valley width BANK_H_M above channel ---
                dx = np.gradient(xs); dy = np.gradient(ys)
                nrm = np.hypot(dx, dy); nrm[nrm == 0] = 1
                px, py = -dy / nrm, dx / nrm          # unit perpendicular
                offs = np.arange(XS_STEP_M, XS_HALF_M, XS_STEP_M)
                widths = np.full(len(xs), np.nan)
                take = slice(None, None, max(1, len(xs) // 40))  # <=40 sections
                for i in np.arange(len(xs))[take]:
                    zc = zs[i]
                    wsum = 0.0
                    for sgn in (1, -1):
                        sx = xs[i] + sgn * px[i] * offs
                        sy = ys[i] + sgn * py[i] * offs
                        zz = sample_grid(arr, tr, sx, sy, nod)
                        above = np.where(zz > zc + BANK_H_M)[0]
                        wsum += offs[above[0]] if len(above) else XS_HALF_M
                    widths[i] = wsum
                wv = widths[~np.isnan(widths)]
                if len(wv) < 2:
                    continue
                valley_w = float(np.median(wv))
                # confinement RELEASE: max downstream widening across the reach
                release = float(np.nanmax(np.diff(wv))) if len(wv) > 1 else 0.0

                # ---- planform curvature (inside bends) ---------------------
                sx2 = uniform_filter1d(xs, w); sy2 = uniform_filter1d(ys, w)
                ddx = np.gradient(np.gradient(sx2)); ddy = np.gradient(np.gradient(sy2))
                curv = float(np.nanmean(np.hypot(ddx, ddy)))
                straight = np.hypot(xs[-1] - xs[0], ys[-1] - ys[0])
                sinuosity = float(line.length / straight) if straight > 1 else 1.0

                # ---- valley-wall steepness (bedrock proxy) ------------------
                wall = float(np.nanmedian(np.abs(np.gradient(wv)))) if len(wv) > 2 else 0.0

                rows.append(dict(segment_id=int(s.segment_id), grad_break=grad_break,
                                 plunge=plunge, valley_w=valley_w, release=release,
                                 curv=curv, sinuosity=sinuosity, wall=wall,
                                 n_samples=len(z)))
    if not rows:
        print("no segments produced trap metrics")
        return 1
    t = pd.DataFrame(rows).set_index("segment_id")
    print(f"\ntrap metrics for {len(t)} segments")

    # ---- normalise to 0-1 by percentile rank within the covered set --------
    def rank01(v, invert=False):
        r = v.rank(pct=True)
        return 1 - r if invert else r

    W = load_weights()
    tmax = W["components"]["trap"]["max"]
    t["f_gradbreak"] = rank01(t.grad_break)
    t["f_release"] = rank01(t.release)
    t["f_confined"] = rank01(t.valley_w, invert=True)   # narrow = confined
    t["f_bend"] = rank01(t.curv)
    t["f_plunge"] = rank01(t.plunge)

    t["trap_score"] = (tmax * (
        0.30 * t.f_gradbreak +      # competence drop — best single signal
        0.20 * t.f_release +        # confinement release
        0.20 * t.f_confined +       # bedrock canyon / crevice ground
        0.15 * t.f_bend +           # inside-bend bars
        0.15 * t.f_plunge           # plunge pools below steps
    )).round(2)

    t.to_parquet(INTERIM / "segment_traps.parquet")
    print(t[["grad_break", "valley_w", "sinuosity", "trap_score"]].describe().round(2).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
