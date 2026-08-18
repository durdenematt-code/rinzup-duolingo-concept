"""Shared paths, config, and helpers for the prospecting pipeline."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
GPKG = ROOT / "data" / "prospect.gpkg"
CONFIG = ROOT / "config"

# Analysis CRS: NAD83 / UTM zone 10N (meters)
CRS = "EPSG:26910"

# Study area bbox in lon/lat (must match the bbox used for the raw extracts)
BBOX_4326 = (-121.95, 47.75, -121.30, 48.10)

# HUC8 whose stream network gets scored (Snohomish). Occurrences outside it
# (Monte Cristo, Silverton — Sauk/Stillaguamish drainages) stay as map
# reference points but never snap to scored segments.
SCORED_HUC8 = "17110009"

# Culmback Dam (Sultan RM 16.5, Spada Lake outlet). Downstream influence
# crossing this point is attenuated by decay.dam_pass_factor.
# "river" constrains the network snap to that river's mainstem level path —
# the raw nearest flowline to a dam coordinate is often a minor tributary.
DAMS = [{"name": "Culmback Dam", "lon": -121.6864, "lat": 47.9822, "river": "Sultan River"}]


def load_weights():
    with open(CONFIG / "weights.yaml") as f:
        return yaml.safe_load(f)


def ensure_dirs():
    RAW.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
