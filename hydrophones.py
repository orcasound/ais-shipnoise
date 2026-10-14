import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from cartopy.io.img_tiles import OSM

from plot_boats import auto_tile_zoom, speed_vector_endpoint

EARTH_RADIUS_KM = 6371.0
SOG_NOT_AVAILABLE = 102.3  # AIS value meaning "speed not available"


@dataclass(frozen=True)
class Site:
    slug: str
    name: str
    lat: float
    lon: float
    az_min: float  # listening zone runs clockwise (true bearing) from az_min to az_max
    az_max: float
    max_range_km: float

    @property
    def stream_node(self):
        """Folder for this node's HLS audio in the Orcasound audio bucket, e.g. rpi_orcasound_lab."""
        return "rpi_" + self.slug.replace("-", "_")


SITES: list[Site] = [
    Site("north-sjc", "North San Juan Channel", 48.5913, -123.0588, 328, 133, 10),
    Site("orcasound-lab", "Orcasound Lab", 48.5583, -123.1736, 166, 329, 10),
    Site("andrews-bay", "Andrews Bay", 48.5467, -123.1664, 176, 319, 10),
    Site("port-townsend", "Port Townsend", 48.1357, -122.7606, 38, 153, 10),
    Site("bush-point", "Bush Point", 48.0337, -122.604, 150, 356, 10),
    Site("sunset-bay", "Sunset Bay", 47.865, -122.3339, 218, 359, 13),
    Site("mast-center", "MaST Center Aquarium", 47.3492, -122.3251, 243, 345, 10),
]
SITES_BY_SLUG: dict[str, Site] = {s.slug: s for s in SITES}


def distance_bearing(lat1, lon1, lat2, lon2):
    """Great-circle distance (km) and initial true bearing (deg) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    distance = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    bearing = math.degrees(math.atan2(y, x)) % 360
    return distance, bearing


def destination(lat, lon, bearing, distance_km):
    """Point reached travelling distance_km from (lat, lon) along the given true bearing."""
    delta = distance_km / EARTH_RADIUS_KM
    theta = math.radians(bearing)
    phi1, lmb1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lmb2 = lmb1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lmb2)


def sector_span(site):
    """Clockwise width of the listening zone in degrees (handles zones that wrap through north)."""
    return (site.az_max - site.az_min) % 360 or 360


def in_sector(bearing, site):
    return (bearing - site.az_min) % 360 <= sector_span(site)


def report_age_minutes(boat, now):
    """Minutes since the boat's last AIS position report, or None if it has no TIME."""
    if not boat.get("TIME"):
        return None
    t = datetime.strptime(boat["TIME"], "%Y-%m-%d %H:%M:%S %Z").replace(tzinfo=ZoneInfo("UTC"))
    return (now - t).total_seconds() / 60


def is_moving(boat, min_sog):
    return min_sog < boat.get("SOG", 0) < SOG_NOT_AVAILABLE


def is_fresh(boat, now, max_age_min):
    age = report_age_minutes(boat, now)
    return age is not None and age <= max_age_min


def boats_near_site(site, boats, now, min_sog=0.5, max_age_min=15):
    """Moving boats with a recent position inside the site's listening zone, nearest first.

    Each result is the AIS record plus DISTANCE_KM and BEARING (from the hydrophone to the boat).
    """
    nearby = []
    for b in boats:
        if not (is_moving(b, min_sog) and is_fresh(b, now, max_age_min)):
            continue
        distance, bearing = distance_bearing(site.lat, site.lon, b["LATITUDE"], b["LONGITUDE"])
        if distance <= site.max_range_km and in_sector(bearing, site):
            nearby.append({**b, "DISTANCE_KM": distance, "BEARING": bearing})
    return sorted(nearby, key=lambda b: b["DISTANCE_KM"])


def site_extent(site, margin=1.15):
    """Square-ish (lon_min, lon_max, lat_min, lat_max) box around the site's maximum range."""
    radius = site.max_range_km * margin
    dlat = radius / 111.32
    dlon = radius / (111.32 * math.cos(math.radians(site.lat)))
    return (site.lon - dlon, site.lon + dlon, site.lat - dlat, site.lat + dlat)


def sector_polygon(site, steps=90):
    """Lon/lat outline of the listening zone wedge."""
    span = sector_span(site)
    arc = [
        destination(site.lat, site.lon, site.az_min + span * i / steps, site.max_range_km)
        for i in range(steps + 1)
    ]
    points = arc if span == 360 else [(site.lat, site.lon), *arc, (site.lat, site.lon)]
    return [p[1] for p in points], [p[0] for p in points]


def plot_site(site, boats, nearby, now, output, vector_minutes=10, min_sog=0.5, max_age_min=15):
    """Map the site's listening zone, the moving boats inside it, and (in gray) other moving boats nearby."""
    extent = site_extent(site)
    tiler = OSM()
    fig = plt.figure(figsize=(7, 7))
    ax = plt.axes(projection=tiler.crs)
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.add_image(tiler, auto_tile_zoom(extent))
    ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

    ring_lons, ring_lats = zip(*[
        destination(site.lat, site.lon, az, site.max_range_km)[::-1] for az in range(0, 361, 4)
    ])
    ax.plot(ring_lons, ring_lats, color="gray", linestyle="--", linewidth=0.8, transform=ccrs.PlateCarree())
    wedge_lons, wedge_lats = sector_polygon(site)
    ax.fill(wedge_lons, wedge_lats, color="tab:blue", alpha=0.15, transform=ccrs.PlateCarree())
    ax.plot(wedge_lons, wedge_lats, color="tab:blue", linewidth=1, transform=ccrs.PlateCarree())

    nearby_mmsi = {b["MMSI"] for b in nearby}
    lon_min, lon_max, lat_min, lat_max = extent
    others = [
        b for b in boats
        if b["MMSI"] not in nearby_mmsi
        and lon_min <= b["LONGITUDE"] <= lon_max and lat_min <= b["LATITUDE"] <= lat_max
        and is_moving(b, min_sog) and is_fresh(b, now, max_age_min)
    ]
    for group, color, size in ((others, "gray", 15), (nearby, "red", 90)):
        if not group:
            continue
        ax.scatter(
            [b["LONGITUDE"] for b in group], [b["LATITUDE"] for b in group],
            color=color, s=size, zorder=5, transform=ccrs.PlateCarree(),
        )
        for b in group:
            end_lat, end_lon = speed_vector_endpoint(
                b["LATITUDE"], b["LONGITUDE"], b.get("COG", 0), b["SOG"], vector_minutes
            )
            arrow = ax.annotate(
                "",
                xy=(end_lon, end_lat),
                xytext=(b["LONGITUDE"], b["LATITUDE"]),
                arrowprops=dict(arrowstyle="->", color="green" if color == "red" else "gray", linewidth=1.2),
                zorder=4,
                transform=ccrs.PlateCarree(),
            )
            arrow.arrow_patch.set_clip_box(ax.bbox)

    # Number each boat's dot with its row in the page's table (nearby is sorted nearest first)
    for n, b in enumerate(nearby, start=1):
        ax.text(
            b["LONGITUDE"], b["LATITUDE"], str(n),
            ha="center", va="center", fontsize=6, fontweight="bold", color="white", zorder=6,
            transform=ccrs.PlateCarree(),
        )

    ax.scatter([site.lon], [site.lat], color="blue", marker="*", s=200, zorder=6, transform=ccrs.PlateCarree())
    ax.set_title(f"{site.name}: {len(nearby)} moving vessel{'s' if len(nearby) != 1 else ''} in zone\n"
                 f"{site.az_min}°–{site.az_max}°, {site.max_range_km} km  ·  "
                 f"{now.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M %Z')}")
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
