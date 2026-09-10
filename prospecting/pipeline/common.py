"""Shared paths, config, and helpers for the prospecting pipeline."""
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
CONFIG = ROOT / "config"

# Analysis CRS: NAD83 / UTM zone 10N (meters). Valid for all WA regions here;
# Blewett/Liberty is near the zone-10/11 seam but well inside 10N.
CRS = "EPSG:26910"

# ---------------------------------------------------------------------------
# REGIONS. Set PROSPECT_REGION to switch; default "puget".
#
# A region is a self-contained study area: its own bbox, HUC8 set, NHDPlus HU4
# geodatabase(s), GeoPackage, and raw-extract filename prefix. Keeping them
# separate rather than growing one bbox matters — Blewett is ~100 km east across
# the Cascade crest, in different river systems AND different counties (so
# different Gold & Fish work windows), and merging it would triple the network
# for no analytical gain.
# ---------------------------------------------------------------------------
REGIONS = {
    "puget": dict(
        label="Skykomish-Stillaguamish-Sauk-Snoqualmie",
        bbox=(-122.30, 47.30, -121.25, 48.35),
        # 17110009 Skykomish, 17110008 Stillaguamish, 17110006 Sauk,
        # 17110011 Snohomish/Pilchuck, 17110010 Snoqualmie
        huc8s=("17110006", "17110008", "17110009", "17110010", "17110011"),
        gdbs=("NHDPLUS_H_1711_HU4_GDB.gdb",),
        prefix="",
        gpkg="prospect.gpkg",
        # Culmback Dam (Sultan RM 16.5): traps upper-basin bedload, so influence
        # crossing it is attenuated by decay.dam_pass_factor.
        dams=[{"name": "Culmback Dam", "lon": -121.6864, "lat": 47.9822,
               "river": "Sultan River"}],
    ),
    "blewett": dict(
        label="Blewett Pass-Liberty-Swauk",
        bbox=(-121.00, 47.05, -120.30, 47.65),
        # 17030001 Upper Yakima (Swauk Ck / Liberty, KITTITAS Co.),
        # 17020011 Wenatchee (Peshastin Ck / Ingalls Ck, CHELAN Co.)
        # Verified against WBDHU8 in the downloaded GDBs.
        huc8s=("17030001", "17020011"),
        gdbs=("NHDPLUS_H_1703_HU4_GDB.gdb", "NHDPLUS_H_1702_HU4_GDB.gdb"),
        prefix="blew_",
        gpkg="prospect_blewett.gpkg",
        dams=[],
    ),
}

REGION = os.environ.get("PROSPECT_REGION", "puget")
if REGION not in REGIONS:
    raise SystemExit(f"unknown PROSPECT_REGION {REGION!r}; have {list(REGIONS)}")
_R = REGIONS[REGION]

BBOX_4326 = _R["bbox"]
SCORED_HUC8S = _R["huc8s"]
NHD_GDBS = [str(RAW / g) for g in _R["gdbs"]]
GPKG = ROOT / "data" / _R["gpkg"]
DAMS = _R["dams"]
REGION_LABEL = _R["label"]


def raw(basename: str) -> Path:
    """Region-scoped raw extract path (e.g. blew_wgs_gold_silver.geojson)."""
    return RAW / f"{_R['prefix']}{basename}"


def raw_all(basename: str):
    """Every existing extract for this basename in the CURRENT region.

    The puget region carries base + king_* strips from its southern expansion;
    other regions use only their own prefix.
    """
    if _R["prefix"]:
        cands = [raw(basename)]
    else:
        cands = [RAW / basename, RAW / f"king_{basename}"]
    return [c for c in cands if c.exists()]


def load_weights(path=None):
    """Load a weight profile. Default: config/weights.yaml (fine/general).
    Pass a path for an alternate profile, e.g. config/weights_coarse.yaml."""
    p = Path(path) if path else CONFIG / "weights.yaml"
    with open(p) as f:
        return yaml.safe_load(f)


def ensure_dirs():
    RAW.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
