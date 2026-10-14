import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from cartopy.io.img_tiles import OSM

from aishub import fetch_by_mmsi
from get_mmsi import get_mmsi_list

# Salish Sea bounding box (lon_min, lon_max, lat_min, lat_max)
EXTENT = (-124.2, -122.0, 47.8, 49.3)

NM_PER_DEG_LAT = 60.0


def auto_tile_zoom(extent):
    """Pick an OSM tile zoom level that keeps the tile count reasonable for the extent's size."""
    span = max(extent[1] - extent[0], extent[3] - extent[2])
    for span_threshold, zoom in ((5, 7), (2, 8), (1, 9), (0.5, 10), (0.2, 12), (0.05, 13)):
        if span > span_threshold:
            return zoom
    return 14


def zoom_extent(extent, factor=2):
    """Shrink an extent around its center to simulate zooming in by the given factor."""
    lon_min, lon_max, lat_min, lat_max = extent
    center_lon = (lon_min + lon_max) / 2
    center_lat = (lat_min + lat_max) / 2
    lon_span = (lon_max - lon_min) / factor
    lat_span = (lat_max - lat_min) / factor
    return (
        center_lon - lon_span / 2,
        center_lon + lon_span / 2,
        center_lat - lat_span / 2,
        center_lat + lat_span / 2,
    )


def speed_vector_endpoint(lat, lon, cog, sog, minutes):
    """Project a boat's position forward along its course, given its speed (in knots)."""
    distance_nm = sog * (minutes / 60)
    angle = math.radians(cog)
    dlat = (distance_nm / NM_PER_DEG_LAT) * math.cos(angle)
    dlon = (distance_nm / (NM_PER_DEG_LAT * math.cos(math.radians(lat)))) * math.sin(angle)
    return lat + dlat, lon + dlon


def latest_boat_time(boats):
    """Return the most recent AIS TIME field among the boats, converted to Pacific time for display."""
    times = [
        datetime.strptime(b["TIME"], "%Y-%m-%d %H:%M:%S %Z").replace(tzinfo=ZoneInfo("UTC"))
        for b in boats
        if b.get("TIME")
    ]
    if not times:
        return None
    pacific = max(times).astimezone(ZoneInfo("America/Los_Angeles"))
    return pacific.strftime ("%Y-%m-%d %H:%M %Z")


def cluster_boats(boats, threshold=0.03):
    clusters = []
    for b in boats:
        for cluster in clusters:
            if any(
                abs(b["LONGITUDE"] - o["LONGITUDE"]) < threshold
                and abs(b["LATITUDE"] - o["LATITUDE"]) < threshold
                for o in cluster
            ):
                cluster.append(b)
                break
        else:
            clusters.append([b])
    return clusters


def plot_boats(
    boats,
    extent=EXTENT,
    title="Whale Watch Boats - Salish Sea",
    output="boats_map.png",
    reference_point=None,
    vector_minutes=10,
    tile_zoom=None,
    zoom_factor=2,
):
    extent = zoom_extent(extent, zoom_factor)

    tiler = OSM()
    fig = plt.figure(figsize=(10, 10))
    ax = plt.axes(projection=tiler.crs)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    zoom = tile_zoom if tile_zoom is not None else auto_tile_zoom(extent)
    ax.add_image(tiler, zoom)
    ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

    lons = [b["LONGITUDE"] for b in boats]
    lats = [b["LATITUDE"] for b in boats]
    ax.scatter(lons, lats, color="red", s=40, zorder=5, transform=ccrs.PlateCarree())

    if vector_minutes:
        for b in boats:
            sog = b.get("SOG", 0)
            if sog <= 0:
                continue
            end_lat, end_lon = speed_vector_endpoint(
                b["LATITUDE"], b["LONGITUDE"], b.get("COG", 0), sog, vector_minutes
            )
            ax.annotate(
                "",
                xy=(end_lon, end_lat),
                xytext=(b["LONGITUDE"], b["LATITUDE"]),
                arrowprops=dict(arrowstyle="->", color="green", linewidth=1.5),
                zorder=4,
                transform=ccrs.PlateCarree(),
            )

    for cluster in cluster_boats(boats):
        for i, b in enumerate(cluster):
            ax.annotate(
                b["NAME"],
                xy=(b["LONGITUDE"], b["LATITUDE"]),
                xytext=(8, 8 - i * 12),
                textcoords="offset points",
                fontsize=8,
                arrowprops=dict(arrowstyle="-", linewidth=0.5, color="black"),
                transform=ccrs.PlateCarree(),
            )

    if reference_point is not None:
        ref_lat, ref_lon, ref_label = reference_point
        ax.scatter(
            [ref_lon], [ref_lat], color="blue", marker="*", s=200, zorder=5,
            transform=ccrs.PlateCarree(),
        )
        ax.annotate(
            ref_label,
            xy=(ref_lon, ref_lat),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            color="blue",
            transform=ccrs.PlateCarree(),
        )

    timestamp = latest_boat_time(boats)
    ax.set_title(f"{title}\n{timestamp}" if timestamp else title)
    plt.savefig(output, dpi=250, bbox_inches="tight")
    plt.show()


if __name__ == "__main__":
    boats = fetch_by_mmsi(get_mmsi_list())

    moving_count = sum(1 for b in boats if b.get("SOG", 0) > 0)
    timestamp = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y%m%d_%H%M%S")
    os.makedirs("plots", exist_ok=True)
    output = f"plots/boats_{timestamp}_{moving_count}moving.png"

    plot_boats(boats, output=output)
