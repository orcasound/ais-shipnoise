"""Build the GitHub Pages site: the whale watch map plus a map of moving boats around each hydrophone node.

Makes a single AISHub area request per run, so both pages share one call against AISHub's rate limit.
"""
import argparse
import html
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt

from aishub import fetch_by_area
from get_mmsi import get_mmsi_list
from hydrophones import SITES, boats_near_site, plot_site
from plot_boats import plot_boats

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Covers the whale watch map and every hydrophone node (latmin, latmax, lonmin, lonmax)
REGION = (47.25, 49.3, -124.2, -122.0)

LIVE_LISTEN_URL = "https://live.orcasound.net/listen/{slug}"

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def vessel_type(code):
    """Broad AIS ship-type category for an AIS type code."""
    if not code:
        return ""
    for low, high, label in (
        (30, 30, "Fishing"), (31, 32, "Towing"), (33, 34, "Dredging/diving"), (35, 35, "Military"),
        (36, 36, "Sailing"), (37, 37, "Pleasure"), (40, 49, "High-speed craft"), (50, 50, "Pilot"),
        (51, 51, "Search & rescue"), (52, 52, "Tug"), (53, 59, "Special craft"),
        (60, 69, "Passenger"), (70, 79, "Cargo"), (80, 89, "Tanker"), (90, 99, "Other"),
    ):
        if low <= code <= high:
            return label
    return ""


def vessel_length(boat):
    """Length in metres from the AIS bow (A) and stern (B) offsets, or None if not reported."""
    a, b = boat.get("A") or 0, boat.get("B") or 0
    return a + b if a and b else None


def render_template(name, **values):
    with open(os.path.join(WEB_DIR, name)) as f:
        page = f.read()
    for key, value in values.items():
        page = page.replace(key, value)
    return page


def site_card(site, nearby, cache_bust):
    if nearby:
        rows = "".join(
            "<tr>"
            f"<td>{n}</td>"
            f"<td>{html.escape(' '.join((b['NAME'] or '').split()) or str(b['MMSI']))}</td>"
            f"<td>{vessel_type(b.get('TYPE'))}</td>"
            f"<td>{vessel_length(b) or ''}</td>"
            f"<td>{b['DISTANCE_KM']:.1f}</td>"
            f"<td>{b['BEARING']:.0f}°</td>"
            f"<td>{b['SOG']:.1f}</td>"
            "</tr>"
            for n, b in enumerate(nearby, start=1)
        )
        table = (
            "<table><thead><tr><th>#</th><th>Vessel</th><th>Type</th><th>Length (m)</th>"
            "<th>Range (km)</th><th>Bearing</th><th>Speed (kn)</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        table = '<p class="none">No moving vessels in the listening zone.</p>'
    img = f"nodes/{site.slug}.png"
    return (
        f'<section class="card" id="{site.slug}">'
        f"<h2>{html.escape(site.name)} <span class=\"count\">{len(nearby)}</span></h2>"
        f'<p class="zone">Listening zone {site.az_min}°–{site.az_max}°, {site.max_range_km} km</p>'
        '<div class="map">'
        f'<a href="{img}"><img src="{img}?v={cache_bust}" alt="Map of moving vessels near {html.escape(site.name)}"></a>'
        f'<a class="listen" href="{LIVE_LISTEN_URL.format(slug=site.slug)}" target="_blank" rel="noopener" '
        f'aria-label="Listen live to {html.escape(site.name)} on live.orcasound.net">&#9654; Listen live</a>'
        "</div>"
        f"{table}</section>"
    )


def build(out_dir):
    os.makedirs(os.path.join(out_dir, "nodes"), exist_ok=True)
    now = datetime.now(ZoneInfo("UTC"))
    updated = now.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z")
    cache_bust = str(int(now.timestamp()))

    boats = fetch_by_area(*REGION)

    ww_mmsi = set(get_mmsi_list())
    ww_boats = [b for b in boats if b["MMSI"] in ww_mmsi]
    plot_boats(
        ww_boats,
        title=f"Whale Watch Boats - Salish Sea ({now.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')})",
        output=os.path.join(out_dir, "whale-watch.png"),
        zoom_factor=3,
    )
    plt.close("all")

    cards = []
    for site in SITES:
        nearby = boats_near_site(site, boats, now)
        plot_site(site, boats, nearby, now, os.path.join(out_dir, "nodes", f"{site.slug}.png"))
        cards.append(site_card(site, nearby, cache_bust))
        print(f"{site.slug}: {len(nearby)} moving vessels in zone")

    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(render_template("index.html"))
    with open(os.path.join(out_dir, "whale-watch.html"), "w") as f:
        f.write(render_template("whale-watch.html", UPDATED_AT=updated, CACHE_BUST=cache_bust))
    with open(os.path.join(out_dir, "hydrophones.html"), "w") as f:
        f.write(render_template("hydrophones.html", UPDATED_AT=updated, SITE_CARDS="\n".join(cards)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the whale watch and hydrophone vessel pages.")
    parser.add_argument("--out", default="_site", help="Output directory (default: _site)")
    build(parser.parse_args().out)
