"""Dynamic ASCII world map renderer using Shapely and Natural Earth GeoJSON."""

from pathlib import Path

from rich.console import Group
from rich.text import Text

# GeoJSON path: bundled Natural Earth 110m land (simplified)
GEOJSON_PATH = Path(__file__).parent.parent / "assets" / "ne_110m_land.geojson"

# Southern latitude limit: exclude Antarctica (peers never there) for better space use
LAT_SOUTH_LIMIT = -60  # degrees; land south of this is excluded

# Land/water characters
LAND = "*"
WATER = " "
MARKER = "●"

# Muted style for land so peer dots stand out. Options to try:
# "#404040" - medium gray
# "#505050" - lighter gray
# "#333333" - darker gray
# "#555555" - soft gray
LAND_STYLE = "#505050"

# 125 distinct colors for peer markers (golden-ratio hue distribution)
PEER_COLORS = [
    "#ed2a2a", "#628ef8", "#a8f23f", "#fb78eb", "#54f6db",
    "#f09931", "#8e6afa", "#4ef546", "#f688ad", "#5cbef9",
    "#e4f339", "#da7af4", "#4ef7a2", "#f1542c", "#6471fb",
    "#85f641", "#f683d0", "#56f3f9", "#f4c333", "#af75f4",
    "#48f865", "#f22640", "#68a2f2", "#c0f63b", "#f67df6",
    "#50fac8", "#f5802d", "#806ff5", "#62f943", "#f885ba",
    "#62cff3", "#f7ee35", "#cc78f7", "#55f18f", "#f63727",
    "#6a88f5", "#9cfa3d", "#f980e0", "#5cf3e6", "#f8ac2f",
    "#9e72f7", "#4ff155", "#f62158", "#64b4f6", "#d3ef42",
    "#e87af9", "#57f4b1", "#f96429", "#6c6df8", "#7cf249",
    "#fb83ca", "#5fe4f6", "#f0d13c", "#bc75fa", "#51f479",
    "#ee2f38", "#6798f8", "#b2f344", "#fb7df2", "#59f7d5",
    "#f19236", "#8b6ffa", "#5bf54b", "#ee2975", "#61c7f9",
    "#edf33e", "#d67ff4", "#53f79d", "#f14f30", "#697dfb",
    "#91f645", "#f687d7", "#5bf9f8", "#f4bb38", "#ac7af5",
    "#4df861", "#f22a4e", "#6cabf3", "#cbf740", "#f082f7",
    "#55fac2", "#f57932", "#7e74f5", "#6ef947", "#f3248e",
    "#67d7f3", "#f7e53a", "#c87cf7", "#59f18a", "#f6322c",
    "#6f92f5", "#a7fa42", "#f985e7", "#61f4df", "#f8a434",
    "#9b77f7", "#56f254", "#f72665", "#69bdf6", "#ddf047",
    "#e37ff9", "#5cf4ac", "#f95e2e", "#7179f8", "#87f24e",
    "#f820aa", "#63ecf6", "#f0c941", "#b87afa", "#56f575",
    "#ee3446", "#6ca2f8", "#bcf348", "#fb82f8", "#5ef7ce",
    "#f18c3b", "#8874fa", "#67f550", "#ef2e81", "#66d0f9",
    "#f4f143", "#d284f5", "#58f898", "#f24a35", "#6e88fb",
]


def _load_geometries() -> list:
    """Load land polygons from GeoJSON. Excludes Antarctica for better space use."""
    import json
    from shapely.geometry import shape

    if not GEOJSON_PATH.exists():
        return []
    data = json.loads(GEOJSON_PATH.read_text())
    features = data.get("features", [])
    geoms = []
    for f in features:
        g = f.get("geometry")
        if g:
            try:
                geom = shape(g)
                # Exclude Antarctica: skip geometries entirely south of LAT_SOUTH_LIMIT
                minx, miny, maxx, maxy = geom.bounds
                if maxy < LAT_SOUTH_LIMIT:
                    continue
                geoms.append(geom)
            except Exception:
                pass
    return geoms


def _build_spatial_index(geometries: list):
    """Build STRtree for fast point-in-polygon queries."""
    from shapely.strtree import STRtree
    return STRtree(geometries)


# Dimmed color for blink animation (when dot is "off")
BLINK_DIM = "#333333"


def generate_map(
    cols: int,
    rows: int,
    markers: list[tuple[float, float]] | None = None,
    center_lon: float | None = None,
    blink_indices: set[int] | None = None,
    blink_visible: bool = True,
) -> str | Group:
    """
    Generate an ASCII world map at the given grid size.
    cols, rows: character grid dimensions.
    markers: optional list of (lat, lon) to place MARKER on the map.
    center_lon: longitude to center the map on (e.g. node location). None = standard -180..180.
    Returns Rich Text or Group (styled with LAND_STYLE for consistency).
    """
    if cols < 10 or rows < 5:
        return Text("(map too small)", style=LAND_STYLE)

    geometries = _load_geometries()
    if not geometries:
        return Text("(map data unavailable)", style=LAND_STYLE)

    try:
        tree = _build_spatial_index(geometries)
    except Exception:
        return Text("(map init failed)", style=LAND_STYLE)

    from shapely.geometry import Point

    # Map rows to lat range: 90°N down to LAT_SOUTH_LIMIT (exclude Antarctica)
    lat_range = 90 - LAT_SOUTH_LIMIT  # e.g. 150 for -60

    # Longitude mapping: center_lon at map center, or standard -180..180
    def lon_at_col(col: int) -> float:
        if center_lon is not None:
            return center_lon - 180 + (col + 0.5) / cols * 360
        return -180 + (col + 0.5) / cols * 360

    def col_for_lon(lon: float) -> int:
        if center_lon is not None:
            offset = ((lon - center_lon + 180) % 360) - 180
            c = int((offset + 180) / 360 * cols)
        else:
            c = int((lon + 180) / 360 * cols)
        return max(0, min(cols - 1, c))

    # Build marker grid: (col, row) -> peer_index (for color assignment)
    # When peers land in same cell, try adjacent cells so all markers are visible
    marker_cells: dict[tuple[int, int], int] = {}
    if markers:
        # Spiral outward: center, then ring of 8, then ring of 16
        offsets = [(0, 0)]
        for r in range(1, 3):
            for dc in range(-r, r + 1):
                for dr in range(-r, r + 1):
                    if abs(dc) == r or abs(dr) == r:
                        offsets.append((dc, dr))
        for peer_idx, (lat, lon) in enumerate(markers):
            base_col = col_for_lon(lon)
            base_row = int((90 - lat) / lat_range * rows)
            base_col = max(0, min(cols - 1, base_col))
            base_row = max(0, min(rows - 1, base_row))
            for dc, dr in offsets:
                c, r = base_col + dc, base_row + dr
                if 0 <= c < cols and 0 <= r < rows and (c, r) not in marker_cells:
                    marker_cells[(c, r)] = peer_idx
                    break
            else:
                marker_cells[(base_col, base_row)] = peer_idx
    line_texts: list[Text] = []
    for row in range(rows):
        lat = 90 - (row + 0.5) / rows * lat_range
        line_text = Text()
        for col in range(cols):
            lon = lon_at_col(col)
            if (col, row) in marker_cells:
                peer_idx = marker_cells[(col, row)]
                if blink_indices and peer_idx in blink_indices and not blink_visible:
                    color = BLINK_DIM
                else:
                    color = PEER_COLORS[peer_idx % len(PEER_COLORS)]
                line_text.append(MARKER, style=color)
            else:
                lon_norm = ((lon + 180) % 360) - 180
                pt = Point(lon_norm, lat)
                found = False
                for idx in tree.query(pt):
                    if geometries[idx].contains(pt):
                        found = True
                        break
                if found:
                    line_text.append(LAND, style=LAND_STYLE)
                else:
                    line_text.append(WATER)
        line_texts.append(line_text)

    return Group(*line_texts)
