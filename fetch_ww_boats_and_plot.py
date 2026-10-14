import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from aishub import fetch_by_mmsi
from get_mmsi import get_mmsi_list
from plot_boats import plot_boats

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch whale watch boat positions from AIShub and plot them.")
    parser.add_argument("--output", help="PNG path to write (default: boats_map_<timestamp>.png)")
    args = parser.parse_args()

    mmsi_list = get_mmsi_list()
    boats = fetch_by_mmsi(mmsi_list)

    call_time = datetime.now(LOCAL_TZ)
    timestamp_label = call_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    timestamp_file = call_time.strftime("%Y%m%d_%H%M%S")

    plot_boats(
        boats,
        title=f"Whale Watch Boats - Salish Sea ({timestamp_label})",
        output=args.output or f"boats_map_{timestamp_file}.png",
        zoom_factor=3,
    )
