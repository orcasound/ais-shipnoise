import bz2
import gzip
import json
import os
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# AIShub username is a credential: read it from the environment (or a local .env file), never commit it.
AISHUB_USERNAME = os.environ.get("AISHUB_USERNAME")
AISHUB_URL = "https://data.aishub.net/ws.php"
RATE_LIMIT_WAIT_S = 65  # AISHub allows about one request per minute per username
SOG_NOT_AVAILABLE = 102.3  # AIS value meaning "speed not available"


def _decompress(content):
    if content[:2] == b"\x1f\x8b":  # gzip magic bytes
        return gzip.decompress(content)
    if content[:3] == b"BZh":  # bzip2 magic bytes
        return bz2.decompress(content)
    return content


def _request(params, username):
    if not username:
        raise RuntimeError("AISHUB_USERNAME is not set; export it or add it to a .env file (see .env.example)")
    params = {"username": username, "format": 1, "output": "json", **params}
    for attempt in range(2):
        response = requests.get(AISHUB_URL, params=params, timeout=30)
        response.raise_for_status()

        data = json.loads(_decompress(response.content))

        meta = data[0]
        if not meta.get("ERROR"):
            break
        if attempt == 0 and "too frequent" in str(meta.get("ERROR_MESSAGE", "")).lower():
            time.sleep(RATE_LIMIT_WAIT_S)
            continue
        raise RuntimeError(f"AISHub API error: {meta}")

    return data[1] if len(data) > 1 else []


def fetch_by_mmsi(mmsi_list, username=AISHUB_USERNAME):
    """Poll AIShub for the current positions of the given MMSIs."""
    return _request({"compress": 2, "mmsi": ",".join(str(m) for m in mmsi_list)}, username)


def fetch_by_area(latmin, latmax, lonmin, lonmax, username=AISHUB_USERNAME):
    """Poll AIShub for vessels within a lat/lon bounding box."""
    return _request(
        {
            "compress": 3,
            "latmin": latmin,
            "latmax": latmax,
            "lonmin": lonmin,
            "lonmax": lonmax,
        },
        username,
    )


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
