"""Private archive of AIShub position reports for moving vessels, stored as Parquet files in S3.

build_site.py calls store_reports() after every AIShub request. Each call writes one small file per report date:
    <ARCHIVE>/report_date=YYYY-MM-DD/<fetch time>.parquet
Files are only ever added, never rewritten, so the GitHub Actions role needs nothing beyond s3:PutObject.

Query (reads with the AWS credentials in .env):
    python ais_db.py query --mmsi 316001234 --class Cargo --start 2026-10-01 --end "2026-10-02 12:00"

AIShub data may not be redistributed: the bucket is private, and report contents must never be printed in CI logs,
committed, or uploaded as Actions artifacts.
"""
import argparse
import csv
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone

import boto3
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from aishub import SOG_NOT_AVAILABLE, vessel_type

# s3://bucket/prefix, or a local directory (for testing)
ARCHIVE = os.environ.get("AIS_ARCHIVE", "s3://orcasound-ais-archive-648183724555-us-west-2-an/ais/reports")
MIN_SOG_KN = 0.5  # same "moving" threshold as the hydrophone pages

SCHEMA = pa.schema([
    ("mmsi", pa.int64()),
    ("report_time", pa.timestamp("s")),  # AIS position time, UTC
    ("fetched_at", pa.timestamp("s")),   # when we received it from AIShub, UTC
    ("latitude", pa.float64()),
    ("longitude", pa.float64()),
    ("sog", pa.float64()),
    ("cog", pa.float64()),
    ("heading", pa.int32()),
    ("rot", pa.int32()),
    ("navstat", pa.int32()),
    ("name", pa.string()),
    ("callsign", pa.string()),
    ("imo", pa.int64()),
    ("type_code", pa.int32()),
    ("vessel_class", pa.string()),
    ("length_m", pa.int32()),
    ("beam_m", pa.int32()),
    ("draught", pa.float64()),
    ("destination", pa.string()),
])


def _utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _text(value):
    return " ".join(str(value).split()) or None if value else None


def _is_moving(boat):
    return MIN_SOG_KN < (boat.get("SOG") or 0) < SOG_NOT_AVAILABLE


def _row(b, fetched):
    a, bb, c, d = (b.get(k) or 0 for k in "ABCD")
    return {
        "mmsi": b["MMSI"],
        "report_time": datetime.strptime(b["TIME"], "%Y-%m-%d %H:%M:%S %Z"),
        "fetched_at": fetched,
        "latitude": b["LATITUDE"],
        "longitude": b["LONGITUDE"],
        "sog": b.get("SOG"),
        "cog": b.get("COG"),
        "heading": b.get("HEADING"),
        "rot": b.get("ROT"),
        "navstat": b.get("NAVSTAT"),
        "name": _text(b.get("NAME")),
        "callsign": _text(b.get("CALLSIGN")),
        "imo": b.get("IMO") or None,
        "type_code": b.get("TYPE") or None,
        "vessel_class": vessel_type(b.get("TYPE")) or None,
        "length_m": a + bb if a and bb else None,
        "beam_m": c + d if c and d else None,
        "draught": b.get("DRAUGHT") or None,
        "destination": _text(b.get("DEST")),
    }


def _split_s3(uri):
    bucket, _, prefix = uri.removeprefix("s3://").partition("/")
    return bucket, prefix.rstrip("/")


def _put(relative_path, data, archive):
    if archive.startswith("s3://"):
        bucket, prefix = _split_s3(archive)
        boto3.client("s3").put_object(Bucket=bucket, Key=f"{prefix}/{relative_path}", Body=data)
    else:
        path = os.path.join(archive, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


def store_reports(boats, fetched_at, archive=ARCHIVE):
    """Save the moving vessels from one AIShub response. Returns the number of reports stored.

    AIShub repeats a vessel's last report until it sends a new one; query_reports() drops those repeats.
    """
    fetched = _utc_naive(fetched_at).replace(microsecond=0)
    rows = [_row(b, fetched) for b in boats if b.get("TIME") and _is_moving(b)]
    by_date = {}
    for row in rows:
        by_date.setdefault(row["report_time"].date(), []).append(row)
    for day, day_rows in by_date.items():
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pylist(day_rows, schema=SCHEMA), buf, compression="zstd")
        _put(f"report_date={day.isoformat()}/{fetched:%Y%m%dT%H%M%SZ}.parquet", buf.getvalue(), archive)
    return len(rows)


def _connect(archive):
    conn = duckdb.connect()
    if archive.startswith("s3://"):
        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials: add AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY to .env")
        creds = creds.get_frozen_credentials()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(
            "CREATE SECRET (TYPE s3, KEY_ID ?, SECRET ?, SESSION_TOKEN ?, REGION ?)",
            [creds.access_key, creds.secret_key, creds.token or "", session.region_name or "us-west-2"],
        )
    return conn


def _as_datetime(value, end=False):
    """Datetime or 'YYYY-MM-DD[ HH:MM[:SS]]' UTC string -> naive UTC datetime. A date-only end means end of day."""
    if isinstance(value, datetime):
        return _utc_naive(value)
    if isinstance(value, date):
        value = value.isoformat()
    dt = datetime.fromisoformat(value)
    if end and len(value) == 10:
        dt += timedelta(days=1, seconds=-1)
    return dt


def query_reports(mmsi=None, vessel_class=None, start=None, end=None, archive=ARCHIVE):
    """Reports oldest first, with AIShub's repeated reports removed. Any filter may be omitted.

    mmsi: one MMSI or a list. vessel_class: one class (e.g. "Cargo") or a list.
    start/end: datetimes or "YYYY-MM-DD[ HH:MM[:SS]]" UTC strings; the range is inclusive.
    """
    where, params = [], []
    for column, value in (("mmsi", mmsi), ("vessel_class", vessel_class)):
        if value is None:
            continue
        values = [value] if isinstance(value, (int, str)) else list(value)
        where.append(f"{column} IN ({','.join('?' * len(values))})")
        params += values
    # report_date filters skip whole partitions, so only the files for the requested days are read
    if start is not None:
        start = _as_datetime(start)
        where += ["report_date >= ?", "report_time >= ?"]
        params += [start.date(), start]
    if end is not None:
        end = _as_datetime(end, end=True)
        where += ["report_date <= ?", "report_time <= ?"]
        params += [end.date(), end]
    source = f"read_parquet('{archive.rstrip('/')}/*/*.parquet', hive_partitioning = true, union_by_name = true)"
    sql = (
        f"SELECT * EXCLUDE (report_date) FROM {source}"
        + (f" WHERE {' AND '.join(where)}" if where else "")
        + " QUALIFY row_number() OVER (PARTITION BY mmsi, report_time ORDER BY fetched_at) = 1"
        " ORDER BY report_time, mmsi"
    )
    conn = _connect(archive)
    try:
        result = conn.execute(sql, params)
    except Exception as e:
        if "No files found" in str(e):
            return []
        raise
    columns = [d[0] for d in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Query the archive of AIShub reports for moving vessels.")
    parser.add_argument("--archive", default=ARCHIVE, help=f"s3:// URI or local directory (default: {ARCHIVE}, or $AIS_ARCHIVE)")
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("query", help="Print matching reports as CSV")
    q.add_argument("--mmsi", type=int, nargs="+", help="One or more MMSI numbers")
    q.add_argument("--class", dest="vessel_class", nargs="+", help='Vessel class(es), e.g. Cargo Tanker "High-speed craft"')
    q.add_argument("--start", help='UTC start, e.g. 2026-10-01 or "2026-10-01 08:00"')
    q.add_argument("--end", help="UTC end (inclusive); a bare date means the end of that day")
    args = parser.parse_args()

    rows = query_reports(args.mmsi, args.vessel_class, args.start, args.end, archive=args.archive)
    if rows:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} reports", file=sys.stderr)


if __name__ == "__main__":
    main()
