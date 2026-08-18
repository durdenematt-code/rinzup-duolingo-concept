"""Inline folium's CDN assets into the exported HTML.

Fetches the exact library versions folium references from the npm registry
(reachable even where CDNs are not) and rewrites the HTML so the map is fully
self-contained/offline except basemap tiles. leaflet.css image references are
converted to data URIs.
"""
import base64
import io
import re
import tarfile
import urllib.request
from pathlib import Path

from common import RAW

CACHE = RAW / "webassets"

# CDN URL substring -> (npm package, version, path inside package)
NPM_MAP = {
    "leaflet@1.9.3/dist/leaflet.js": ("leaflet", "1.9.3", "dist/leaflet.js"),
    "leaflet@1.9.3/dist/leaflet.css": ("leaflet", "1.9.3", "dist/leaflet.css"),
    "jquery-3.7.1.min.js": ("jquery", "3.7.1", "dist/jquery.min.js"),
    "bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js": ("bootstrap", "5.2.2", "dist/js/bootstrap.bundle.min.js"),
    "bootstrap@5.2.2/dist/css/bootstrap.min.css": ("bootstrap", "5.2.2", "dist/css/bootstrap.min.css"),
    "d3/3.5.5/d3.min.js": ("d3", "3.5.5", "d3.min.js"),
    "Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js": ("drmonty-leaflet-awesome-markers", "2.0.2", "js/leaflet.awesome-markers.min.js"),
    "Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css": ("drmonty-leaflet-awesome-markers", "2.0.2", "css/leaflet.awesome-markers.css"),
}

_tarballs: dict = {}


def _npm_file(pkg: str, ver: str, path: str) -> bytes | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tgz = CACHE / f"{pkg.replace('/', '_')}-{ver}.tgz"
    if not tgz.exists():
        url = f"https://registry.npmjs.org/{pkg}/-/{pkg.split('/')[-1]}-{ver}.tgz"
        try:
            urllib.request.urlretrieve(url, tgz)
        except Exception as e:
            print(f"  webassets: could not fetch {pkg}@{ver}: {e}")
            return None
    key = str(tgz)
    if key not in _tarballs:
        _tarballs[key] = tarfile.open(tgz)
    tf = _tarballs[key]
    try:
        return tf.extractfile(f"package/{path}").read()
    except KeyError:
        print(f"  webassets: {path} not in {pkg}@{ver}")
        return None


def _inline_leaflet_css_images(css: str, pkg: str, ver: str) -> str:
    def repl(mm):
        img = _npm_file(pkg, ver, f"dist/images/{mm.group(1)}")
        if img is None:
            return mm.group(0)
        b64 = base64.b64encode(img).decode()
        return f"url(data:image/png;base64,{b64})"
    return re.sub(r"url\(images/([\w.-]+\.png)\)", repl, css)


def inline_assets(html_path: Path) -> None:
    html = html_path.read_text()
    replaced, left = 0, []

    for m in re.finditer(r'<script src="([^"]+)"></script>', html):
        url = m.group(1)
        hit = next((v for k, v in NPM_MAP.items() if k in url), None)
        body = _npm_file(*hit) if hit else None
        if body is not None:
            html = html.replace(m.group(0), f"<script>\n{body.decode()}\n</script>")
            replaced += 1
        else:
            left.append(url)

    for m in re.finditer(r'<link rel="stylesheet" href="([^"]+)"\s*/?>', html):
        url = m.group(1)
        hit = next((v for k, v in NPM_MAP.items() if k in url), None)
        body = _npm_file(*hit) if hit else None
        if body is not None:
            css = body.decode()
            if "leaflet.css" in url:
                css = _inline_leaflet_css_images(css, hit[0], hit[1])
            html = html.replace(m.group(0), f"<style>\n{css}\n</style>")
            replaced += 1
        else:
            left.append(url)

    html_path.write_text(html)
    print(f"  webassets: inlined {replaced} assets; left as CDN refs: {len(left)}")
    for u in left:
        print(f"    (cdn) {u[:100]}")
