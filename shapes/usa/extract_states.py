"""Extract individual state SVGs from a combined US states SVG.

For states with multiple disconnected landmasses (e.g. Hawaii, Michigan),
connects them with thin rectangles so the shape is one printable piece.
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from svgpathtools import parse_path, Path as SvgPath

CLASS_TO_ABBR = {
    "al": "AL", "ak": "AK", "az": "AZ", "ar": "AR", "ca": "CA",
    "co": "CO", "ct": "CT", "de": "DE", "fl": "FL", "ga": "GA",
    "hi": "HI", "id": "ID", "il": "IL", "in": "IN", "ia": "IA",
    "ks": "KS", "ky": "KY", "la": "LA", "me": "ME", "md": "MD",
    "ma": "MA", "mi": "MI", "mn": "MN", "ms": "MS", "mo": "MO",
    "mt": "MT", "ne": "NE", "nv": "NV", "nh": "NH", "nj": "NJ",
    "nm": "NM", "ny": "NY", "nc": "NC", "nd": "ND", "oh": "OH",
    "ok": "OK", "or": "OR", "pa": "PA", "ri": "RI", "sc": "SC",
    "sd": "SD", "tn": "TN", "tx": "TX", "ut": "UT", "vt": "VT",
    "va": "VA", "wa": "WA", "wv": "WV", "wi": "WI", "wy": "WY",
}

STRIP_WIDTH_FRAC = 0.015


def split_parsed_path_into_subpaths(path: SvgPath) -> list[SvgPath]:
    """Split a parsed svgpathtools Path into continuous subpaths."""
    if len(path) == 0:
        return []
    subpaths = []
    current = []
    for seg in path:
        if current and abs(seg.start - current[-1].end) > 1e-3:
            subpaths.append(SvgPath(*current))
            current = []
        current.append(seg)
    if current:
        subpaths.append(SvgPath(*current))
    return subpaths


def make_connecting_rect(cx1, cy1, cx2, cy2, width):
    dx = cx2 - cx1
    dy = cy2 - cy1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-6:
        return ""
    nx = -dy / length * width / 2
    ny = dx / length * width / 2
    x1, y1 = cx1 + nx, cy1 + ny
    x2, y2 = cx1 - nx, cy1 - ny
    x3, y3 = cx2 - nx, cy2 - ny
    x4, y4 = cx2 + nx, cy2 + ny
    return f"M{x1:.2f},{y1:.2f}L{x4:.2f},{y4:.2f}L{x3:.2f},{y3:.2f}L{x2:.2f},{y2:.2f}Z"


def find_closest_points(sp1: SvgPath, sp2: SvgPath, samples=40):
    """Find approximate closest points between two subpaths."""
    min_dist = float('inf')
    best = (0, 0, 0, 0)
    pts1 = [sp1.point(i / samples) for i in range(samples)]
    pts2 = [sp2.point(i / samples) for i in range(samples)]
    for p1 in pts1:
        for p2 in pts2:
            dist = abs(p1 - p2)
            if dist < min_dist:
                min_dist = dist
                best = (p1.real, p1.imag, p2.real, p2.imag)
    return best, min_dist


def process_state(class_name: str, path_d: str, out_dir: Path):
    abbr = CLASS_TO_ABBR.get(class_name)
    if not abbr:
        return None

    full_path = parse_path(path_d)
    if full_path.length() < 1e-6:
        return None

    xmin, xmax, ymin, ymax = full_path.bbox()
    w = xmax - xmin
    h = ymax - ymin
    if w < 1e-6 or h < 1e-6:
        return None

    subpaths = split_parsed_path_into_subpaths(full_path)
    # Filter out tiny subpaths (< 1% of total area diagonal)
    diag = math.sqrt(w * w + h * h)
    sig_subpaths = []
    for sp in subpaths:
        try:
            sxmin, sxmax, symin, symax = sp.bbox()
            sp_diag = math.sqrt((sxmax - sxmin) ** 2 + (symax - symin) ** 2)
            if sp_diag > diag * 0.01:
                sig_subpaths.append(sp)
        except Exception:
            sig_subpaths.append(sp)

    multi = len(sig_subpaths) > 1
    strip_w = diag * STRIP_WIDTH_FRAC

    connectors = []
    if multi and len(sig_subpaths) > 1:
        # MST: connect subpaths greedily by closest pair
        connected = {0}
        remaining = set(range(1, len(sig_subpaths)))
        while remaining:
            best_dist = float('inf')
            best_j = None
            best_pts = None
            for i in connected:
                for j in remaining:
                    pts, dist = find_closest_points(sig_subpaths[i], sig_subpaths[j])
                    if dist < best_dist:
                        best_dist = dist
                        best_j = j
                        best_pts = pts
            if best_j is not None:
                connected.add(best_j)
                remaining.discard(best_j)
                cx1, cy1, cx2, cy2 = best_pts
                rect = make_connecting_rect(cx1, cy1, cx2, cy2, strip_w)
                if rect:
                    connectors.append(rect)
            else:
                break

    all_d = path_d
    for c in connectors:
        all_d += " " + c

    margin_frac = 0.05
    mx = w * margin_frac
    my = h * margin_frac
    vx = xmin - mx
    vy = ymin - my
    vw = w + 2 * mx
    vh = h + 2 * my

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}">\n'
        f'<path fill="black" d="{all_d}"/>\n'
        f'</svg>\n'
    )

    out_path = out_dir / f"{abbr}.svg"
    out_path.write_text(svg)
    return abbr, multi, len(sig_subpaths), len(connectors)


def main():
    src = Path("states.svg")
    out_dir = Path("states")
    out_dir.mkdir(exist_ok=True)

    tree = ET.parse(src)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}

    results = []
    for g in root.findall(".//svg:g[@class='state']", ns):
        for path in g.findall("svg:path", ns):
            cls = path.get("class", "").strip()
            d = path.get("d", "").strip()
            if cls == "dc":
                continue
            if not d:
                continue
            result = process_state(cls, d, out_dir)
            if result:
                abbr, multi, n_sub, n_conn = result
                status = f"  {abbr}: {n_sub} landmass(es)" + (f", {n_conn} connector(s)" if n_conn else "")
                results.append(status)
                if multi:
                    print(f"  ** {abbr}: {n_sub} landmasses, added {n_conn} connector(s)")

    print(f"\nExtracted {len(results)} states to {out_dir}/")
    for r in sorted(results):
        print(r)


if __name__ == "__main__":
    main()
