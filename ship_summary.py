"""Summarize the vessels in the private AIS archive within a UTC date range and a lat/lon box.

One row per vessel: identity, how many reports and separate visits fell in the box, when it was first and last
seen there, its speeds, and the destinations it broadcast. A per-class total follows.

    python ship_summary.py --start 2026-10-19 --end 2026-10-23                  # default box: Anacortes
    python ship_summary.py --bbox 48.40 48.60 -122.80 -122.50 --class Tanker --csv anacortes.csv

Reads with the AWS credentials in .env, like ais_db.py. The output is AIShub data: keep it within the project.
"""
import argparse
import csv
import sys
from collections import defaultdict
from datetime import timedelta

import ais_db

# Named boxes (latmin, latmax, lonmin, lonmax)
BOXES = {
    # Guemes Channel, Ship Harbor ferry terminal, Cap Sante, Fidalgo Bay, March Point refinery piers and west
    # Padilla Bay. The west edge stops short of the Rosario Strait traffic lanes so through traffic is left out.
    "anacortes": (48.46, 48.545, -122.70, -122.50),
}

FIELDS = [
    "mmsi", "name", "vessel_class", "length_m", "reports", "visits", "first_seen", "last_seen", "hours_in_box",
    "mean_sog", "max_sog", "destinations",
]


def summarize(reports, visit_gap):
    """One dict per vessel. A new visit starts when a vessel goes visit_gap without a report in the box."""
    by_mmsi = defaultdict(list)
    for r in reports:
        by_mmsi[r["mmsi"]].append(r)
    vessels = []
    for mmsi, rs in by_mmsi.items():
        visits = [[rs[0]]]
        for prev, r in zip(rs, rs[1:]):
            if r["report_time"] - prev["report_time"] > visit_gap:
                visits.append([])
            visits[-1].append(r)
        speeds = [r["sog"] for r in rs if r["sog"] is not None]
        last = lambda key: next((r[key] for r in reversed(rs) if r[key]), None)  # noqa: E731
        vessels.append({
            "mmsi": mmsi,
            "name": last("name"),
            "vessel_class": last("vessel_class"),
            "length_m": last("length_m"),
            "reports": len(rs),
            "visits": len(visits),
            "first_seen": rs[0]["report_time"],
            "last_seen": rs[-1]["report_time"],
            "hours_in_box": round(sum((v[-1]["report_time"] - v[0]["report_time"]).total_seconds() for v in visits) / 3600, 1),
            "mean_sog": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "max_sog": max(speeds) if speeds else None,
            "destinations": "; ".join(dict.fromkeys(r["destination"] for r in rs if r["destination"])),
        })
    return sorted(vessels, key=lambda v: (v["vessel_class"] or "~", -v["visits"], v["name"] or ""))


def class_totals(vessels):
    totals = defaultdict(lambda: {"vessels": 0, "visits": 0})
    for v in vessels:
        t = totals[v["vessel_class"] or "Unknown"]
        t["vessels"] += 1
        t["visits"] += v["visits"]
    return sorted(totals.items(), key=lambda kv: -kv[1]["visits"])


def _cell(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def print_table(rows, fields, out=sys.stdout, max_width=40):
    cells = [[_cell(r[f])[:max_width] for f in fields] for r in rows]
    widths = [max([len(f)] + [len(c[i]) for c in cells]) for i, f in enumerate(fields)]
    print("  ".join(f.ljust(w) for f, w in zip(fields, widths)), file=out)
    print("  ".join("-" * w for w in widths), file=out)
    for c in cells:
        print("  ".join(v.ljust(w) for v, w in zip(c, widths)), file=out)


def main():
    parser = argparse.ArgumentParser(description="Summarize archived vessels by date range and lat/lon box.")
    parser.add_argument("--start", help='UTC start, e.g. 2026-10-01 or "2026-10-01 08:00" (default: start of archive)')
    parser.add_argument("--end", help="UTC end (inclusive); a bare date means the end of that day (default: now)")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--box", choices=sorted(BOXES), default="anacortes", help="Named box (default: anacortes)")
    where.add_argument("--bbox", type=float, nargs=4, metavar=("LATMIN", "LATMAX", "LONMIN", "LONMAX"),
                       help="Custom box in decimal degrees (west longitudes negative)")
    parser.add_argument("--class", dest="vessel_class", nargs="+", help='Vessel class(es), e.g. Cargo Tanker "Tug"')
    parser.add_argument("--visit-gap", type=float, default=60,
                        help="Minutes without a report that end one visit (default: 60)")
    parser.add_argument("--csv", help="Also write the per-vessel table to this CSV file")
    parser.add_argument("--archive", default=ais_db.ARCHIVE, help="s3:// URI or local directory (default: %(default)s)")
    args = parser.parse_args()

    bbox = tuple(args.bbox) if args.bbox else BOXES[args.box]
    reports = ais_db.query_reports(vessel_class=args.vessel_class, start=args.start, end=args.end, bbox=bbox,
                                   archive=args.archive)
    vessels = summarize(reports, timedelta(minutes=args.visit_gap))

    label = f"{args.box} " if not args.bbox else ""
    print(f"Box {label}lat {bbox[0]}..{bbox[1]}, lon {bbox[2]}..{bbox[3]}; "
          f"UTC {args.start or 'start'} .. {args.end or 'now'}")
    print(f"{len(vessels)} vessels, {sum(v['visits'] for v in vessels)} visits, {len(reports)} reports\n")
    if not vessels:
        return
    print_table(vessels, FIELDS)
    print()
    print_table([{"vessel_class": c, **t} for c, t in class_totals(vessels)], ["vessel_class", "vessels", "visits"])

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(vessels)
        print(f"\nWrote {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
