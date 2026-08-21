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

# Study area bbox in lon/lat (must match the bbox used for the raw extracts).
# V0.2: expanded north/west from the original Sultan–Gold Bar–Index corridor to
# take in the Monte Cristo district, the Mountain Loop Highway corridor
# (Silverton), and the country around Granite Falls and Arlington.
BBOX_4326 = (-122.30, 47.30, -121.25, 48.35)  # V0.3.1: south past the North
# Bend front (McClellan Butte / Mt Washington) so the Snoqualmie batholith
# margin isn't sitting on the coverage edge

# HUC8s whose stream networks get scored (names from WBDHU8 in the NHDPlus GDB):
#   17110009 Skykomish      — Sultan/Wallace/Skykomish (original V0.1 area)
#   17110008 Stillaguamish  — SF Stilly (Granite Falls, Silverton), NF Stilly (Arlington–Oso)
#   17110006 Sauk           — SF Sauk headwaters (Monte Cristo) down to Darrington
#   17110011 Snohomish      — Pilchuck River side of Granite Falls
#   17110010 Snoqualmie     — King Co. east: Tolt R., Miller River / Buena Vista /
#                             Taylor River / Snoqualmie districts (V0.3)
# Basins are clipped to BBOX_4326; navigation truncates at the bbox edge.
SCORED_HUC8S = ("17110006", "17110008", "17110009", "17110010", "17110011")

# Culmback Dam (Sultan RM 16.5, Spada Lake outlet). Downstream influence
# crossing this point is attenuated by decay.dam_pass_factor.
# "river" constrains the network snap to that river's mainstem level path —
# the raw nearest flowline to a dam coordinate is often a minor tributary.
DAMS = [{"name": "Culmback Dam", "lon": -121.6864, "lat": 47.9822, "river": "Sultan River"}]


def load_weights(path=None):
    """Load a weight profile. Default: config/weights.yaml (fine/general).
    Pass a path for an alternate profile, e.g. config/weights_coarse.yaml."""
    p = Path(path) if path else CONFIG / "weights.yaml"
    with open(p) as f:
        return yaml.safe_load(f)


def ensure_dirs():
    RAW.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
