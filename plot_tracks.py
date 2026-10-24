"""Map the tracks of archived vessels of given class(es) that passed through a lat/lon box in a UTC time range.

Each pass through the box is drawn from --pad hours before the vessel's first report in the box to --pad hours after
its last one, so the map shows where it came from and where it went. Arrowheads mark the direction of travel.

    python plot_tracks.py --class Tanker --start 2026-10-19 --end 2026-10-23          # default box: Anacortes
    python plot_tracks.py --class Tug Towing --bbox 48.40 48.60 -122.80 -122.50 --pad 3 --show

Reads with the AWS credentials in .env, like ais_db.py. The map shows AIShub data: keep it within the project.
"""
import argparse
import os
from collections import defaultdict
from datetime import timedelta

import cartopy.crs as ccrs
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from cartopy.io.img_tiles import OSM

import ais_db
from plot_boats import auto_tile_zoom
from ship_summary import BOXES

# Categorical colors in fixed order; vessels beyond the eighth are drawn in OTHER_COLOR
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER_COLOR = "#8a8a85"
BOX_COLOR = "#222222"


def passes(hits, gap):
    """{mmsi: [(first, last), ...]}: the reports in the box, split where a vessel goes `gap` without one."""
    by_mmsi = defaultdict(list)
    for r in hits:
        times = by_mmsi[r["mmsi"]]
        if times and r["report_time"] - times[-1][1] <= gap:
            times[-1][1] = r["report_time"]
        else:
            times.append([r["report_time"], r["report_time"]])
    return {mmsi: [tuple(t) for t in times] for mmsi, times in by_mmsi.items()}


def segments(reports, windows, pad, max_gap):
    """Lists of reports to draw as lines: each pass widened by `pad`, overlapping passes merged, broken at gaps."""
    merged = []
    for first, last in windows:
        lo, hi = first - pad, last + pad
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    out = []
    for lo, hi in merged:
        current = []
        for r in reports:
            if not lo <= r["report_time"] <= hi:
                continue
            if current and r["report_time"] - current[-1]["report_time"] > max_gap:
                out.append(current)
                current = []
            current.append(r)
        if current:
            out.append(current)
    return out


def fit_extent(points, bbox, margin=0.1, min_span=0.15):
    """(lon_min, lon_max, lat_min, lat_max) around the tracks and the box."""
    lats = [p[0] for p in points] + [bbox[0], bbox[1]]
    lons = [p[1] for p in points] + [bbox[2], bbox[3]]
    lat_pad = max(max(lats) - min(lats), min_span) * margin
    lon_pad = max(max(lons) - min(lons), min_span) * margin
    return min(lons) - lon_pad, max(lons) + lon_pad, min(lats) - lat_pad, max(lats) + lat_pad


def plot_tracks(tracks, bbox, title, output, tile_zoom=None, show=False):
    """tracks: [(label, [segment, ...]), ...] in color order; each segment a list of reports, oldest first."""
    points = [(r["latitude"], r["longitude"]) for _, segs in tracks for seg in segs for r in seg]
    extent = fit_extent(points, bbox)

    tiler = OSM()
    fig = plt.figure(figsize=(10, 10))
    ax = plt.axes(projection=tiler.crs)
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.add_image(tiler, tile_zoom if tile_zoom is not None else auto_tile_zoom(extent))
    ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

    latmin, latmax, lonmin, lonmax = bbox
    ax.add_patch(mpatches.Rectangle(
        (lonmin, latmin), lonmax - lonmin, latmax - latmin, fill=False, edgecolor=BOX_COLOR, linewidth=1.5,
        linestyle="--", zorder=3, transform=ccrs.PlateCarree(),
    ))

    handles = []
    for i, (label, segs) in enumerate(tracks):
        other = i >= len(COLORS)
        color = OTHER_COLOR if other else COLORS[i]
        for seg in segs:
            lons = [r["longitude"] for r in seg]
            lats = [r["latitude"] for r in seg]
            ax.plot(lons, lats, color=color, linewidth=1.2 if other else 2, alpha=0.9, zorder=4,
                    transform=ccrs.PlateCarree())
            ax.scatter(lons[:1], lats[:1], color=color, s=16, edgecolors="white", linewidths=1, zorder=5,
                       transform=ccrs.PlateCarree())
            # arrowheads at the middle and end of the segment show the direction of travel
            for j in {len(seg) // 2, len(seg) - 1} - {0}:
                ax.annotate("", xy=(lons[j], lats[j]), xytext=(lons[j - 1], lats[j - 1]),
                            arrowprops=dict(arrowstyle="-|>", color=color, linewidth=0, mutation_scale=14),
                            zorder=5, transform=ccrs.PlateCarree())
        if not other:
            handles.append(plt.Line2D([], [], color=color, linewidth=2, label=label))
    if len(tracks) > len(COLORS):
        handles.append(plt.Line2D([], [], color=OTHER_COLOR, linewidth=1.2,
                                  label=f"{len(tracks) - len(COLORS)} other vessels"))
    handles.append(plt.Line2D([], [], color=BOX_COLOR, linewidth=1.5, linestyle="--", label="Selection box"))
    ax.legend(handles=handles, loc="best", fontsize=8, framealpha=0.9)

    ax.set_title(title)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    plt.savefig(output, dpi=200, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Map tracks of vessels of given class(es) that passed through a box.")
    parser.add_argument("--class", dest="vessel_class", nargs="+", required=True,
                        help='Vessel class(es), e.g. Tanker Cargo "Tug"')
    parser.add_argument("--start", help='UTC start, e.g. 2026-10-01 or "2026-10-01 08:00" (default: start of archive)')
    parser.add_argument("--end", help="UTC end (inclusive); a bare date means the end of that day (default: now)")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--box", choices=sorted(BOXES), default="anacortes", help="Named box (default: anacortes)")
    where.add_argument("--bbox", type=float, nargs=4, metavar=("LATMIN", "LATMAX", "LONMIN", "LONMAX"),
                       help="Custom box in decimal degrees (west longitudes negative)")
    parser.add_argument("--mmsi", type=int, nargs="+", help="Only these vessels")
    parser.add_argument("--pad", type=float, default=6, help="Hours of track to show before and after each pass (default: 6)")
    parser.add_argument("--max-gap", type=float, default=120,
                        help="Minutes without a report that break a track line (default: 120)")
    parser.add_argument("--zoom", type=int, help="OSM tile zoom level (default: chosen from the map size)")
    parser.add_argument("--output", help="PNG path (default: plots/tracks_<class>_<box>_<start>_<end>.png)")
    parser.add_argument("--show", action="store_true", help="Also open the map in a window")
    parser.add_argument("--archive", default=ais_db.ARCHIVE, help="s3:// URI or local directory (default: %(default)s)")
    args = parser.parse_args()

    bbox = tuple(args.bbox) if args.bbox else BOXES[args.box]
    hits = ais_db.query_reports(mmsi=args.mmsi, vessel_class=args.vessel_class, start=args.start, end=args.end,
                                bbox=bbox, archive=args.archive)
    windows = passes(hits, timedelta(hours=1))
    if not windows:
        print("No matching vessels passed through the box.")
        return

    # the full tracks, outside the box too, within the selected time range
    reports = ais_db.query_reports(mmsi=list(windows), start=args.start, end=args.end, archive=args.archive)
    by_mmsi = defaultdict(list)
    for r in reports:
        by_mmsi[r["mmsi"]].append(r)

    pad, max_gap = timedelta(hours=args.pad), timedelta(minutes=args.max_gap)
    tracks = []
    for mmsi, ws in windows.items():
        name = next((r["name"] for r in reversed(by_mmsi[mmsi]) if r["name"]), str(mmsi))
        label = f"{name} ({len(ws)} pass{'es' if len(ws) > 1 else ''})"
        tracks.append((label, segments(by_mmsi[mmsi], ws, pad, max_gap)))
    tracks.sort(key=lambda t: -sum(len(s) for s in t[1]))  # the vessels with the most track get the colors

    classes = " / ".join(args.vessel_class)
    where_label = "custom box" if args.bbox else f"{args.box} box"
    span = f"{args.start or 'start'} to {args.end or 'now'} UTC"
    slug = "-".join(c.replace(" ", "") for c in args.vessel_class)
    output = args.output or os.path.join(
        "plots", f"tracks_{slug}_{'bbox' if args.bbox else args.box}_{args.start or 'start'}_{args.end or 'now'}.png"
    ).replace(" ", "T").replace(":", "")
    plot_tracks(tracks, bbox, f"{classes} tracks through the {where_label}\n{span}, ±{args.pad:g} h around each pass",
                output, tile_zoom=args.zoom, show=args.show)
    print(f"{len(tracks)} vessels, {sum(len(ws) for ws in windows.values())} passes -> {output}")


if __name__ == "__main__":
    main()
