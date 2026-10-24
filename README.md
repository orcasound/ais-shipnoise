# ais-shipnoise

Fetches current AIS positions of Salish Sea whale watch boats from [AISHub](https://www.aishub.net/) and plots them on an OpenStreetMap basemap.

Live pages (rebuilt every ~15 min by GitHub Actions):
- Whale watch boats: https://orcasound.github.io/ais-shipnoise/whale-watch.html
- Moving vessels near each hydrophone node: https://orcasound.github.io/ais-shipnoise/hydrophones.html

Each run makes a single AISHub area request (`build_site.py`) that feeds both pages, keeping well under AISHub's rate limit.
Each node map has an inline live-audio player that streams the node's HLS feed from the Orcasound audio bucket (`Site.stream_node`).
Hydrophone nodes and their listening zones (bearing range, clockwise, and max range in km) are defined in `hydrophones.py`.

## Local use

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your AISHub username in .env
python fetch_ww_boats_and_plot.py              # writes boats_map_<timestamp>.png
python fetch_ww_boats_and_plot.py --output x.png
python build_site.py --out _site               # builds both pages, as the GitHub Action does
```

Boats to track are listed in `whale_watch_boats.txt`.

## Report archive

Every `build_site.py` run saves the reports for moving vessels (SOG > 0.5 kn) to a **private** S3 bucket,
`orcasound-ais-archive-648183724555-us-west-2-an` (us-west-2), as one small Parquet file per run under
`ais/reports/report_date=YYYY-MM-DD/`. AIShub data may not be redistributed: keep the bucket private and never
commit, publish or log report contents. Archiving is best effort, so an S3 failure only warns and the pages still build.

Query with the read-only keys in `.env` (reports AIShub repeated in later requests are dropped):

```bash
python ais_db.py query --mmsi 316001234 > ship.csv               # by MMSI (one or more)
python ais_db.py query --class Cargo Tanker --start 2026-10-01 --end 2026-10-07   # by class and UTC time range
```

Classes are the broad AIS ship-type categories shown on the hydrophone page (Cargo, Tanker, Passenger, Tug, ...).
From Python: `ais_db.query_reports(mmsi=..., vessel_class=..., start=..., end=..., bbox=(latmin, latmax, lonmin, lonmax))`.

Set `AIS_ARCHIVE` to a local directory to write and query a local archive instead (for testing).

Access (AWS account 648183724555):
- GitHub Actions uses the IAM role `ais-shipnoise-writer` via OIDC (no stored keys); it may only `s3:PutObject` under `ais/`,
  and only from `main` of this repo.
- The IAM user `ais-archive-reader` may only list and read under `ais/`; its keys go in your local `.env`.

## Querying the archive

Access is for Orcasound collaborators only; ask the archive's maintainer for read access. You will get your own
read-only AWS access key (members of the IAM group `ais-archive-readers`). Keep it in your local `.env` only: never
commit, email or post it, and do not share query results outside the project.

```bash
git clone https://github.com/orcasound/ais-shipnoise.git
cd ais-shipnoise
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (AISHUB_USERNAME is not needed)
python ais_db.py query --class Cargo Tanker --start 2026-10-19 > cargo.csv
```

Options (all optional, combine as needed; times are UTC):
- `--mmsi 316001234 [...]`: one or more MMSI numbers
- `--class Cargo Tanker [...]`: vessel classes; quote multi-word ones, e.g. `"High-speed craft"`
- `--start 2026-10-19` / `--end "2026-10-20 12:00"`: write dates as `YYYY-MM-DD`; an end date on its own covers that whole day

The CSV goes to standard output and the number of reports to standard error. Data starts on 2026-10-19 (UTC).
In PyCharm, put the options (e.g. `query --class Cargo`) in the run configuration's **Script parameters** and set the
working directory to the repository folder so `.env` is found. From Python, `ais_db.query_reports(...)` returns a list
of dicts (`pandas.DataFrame(rows)` makes a table).

If boto3 fails to import with `cannot import name ... from 'botocore...'`, boto3 and botocore are mismatched:
install matching versions, e.g. `pip install "boto3==1.43.0" "botocore==1.43.0"`.

## Traffic in an area: `ship_summary.py` and `plot_tracks.py`

Two scripts look at the vessels that passed through a lat/lon box over a UTC time range. They read the archive with
the same `.env` keys as `ais_db.py`, and their output is AIShub data: keep tables and maps within the project.

The box is either a named box from `BOXES` in `ship_summary.py` (`--box`, default `anacortes`) or your own
(`--bbox LATMIN LATMAX LONMIN LONMAX`, decimal degrees, west longitudes negative). Add a named box to `BOXES` and both
scripts can use it.

The `anacortes` box (lat 48.46 to 48.545, lon -122.70 to -122.50) covers Guemes Channel, the Ship Harbor ferry
terminal, Cap Sante, Fidalgo Bay, the March Point refinery piers and western Padilla Bay. Its west edge stops short of
the Rosario Strait traffic lanes, so through traffic in the strait is left out. Vessels going between Rosario Strait and
Bellingham Channel through Guemes Channel (for example tankers bound for Cherry Point) do cross it.

### Summary table

```bash
python ship_summary.py --start 2026-10-19 --end 2026-10-23                       # Anacortes box
python ship_summary.py --class Tanker Tug --start 2026-10-19 --csv anacortes.csv
python ship_summary.py --bbox 48.40 48.60 -122.80 -122.50 --visit-gap 30
```

| Option | Meaning |
|---|---|
| `--start`, `--end` | UTC range, as in `ais_db.py`; both optional (default: whole archive) |
| `--box` / `--bbox` | the area (see above) |
| `--class` | only these vessel classes, e.g. `Tanker "High-speed craft"` |
| `--visit-gap` | minutes without a report in the box that end one visit (default 60) |
| `--csv FILE` | also write the per-vessel table to a CSV file |

It prints one row per vessel, then the number of vessels and visits per class:

| Column | Meaning |
|---|---|
| `mmsi`, `name`, `vessel_class`, `length_m` | identity (latest non-empty value) |
| `reports` | archived reports inside the box |
| `visits` | separate passes through the box (split by `--visit-gap`) |
| `first_seen`, `last_seen` | first and last report in the box, UTC |
| `hours_in_box` | summed time from first to last report of each visit |
| `mean_sog`, `max_sog` | speed over ground in the box, knots |
| `destinations` | destinations the vessel broadcast while in the box |

### Track maps

```bash
python plot_tracks.py --class Tanker --start 2026-10-19 --end 2026-10-23
python plot_tracks.py --class Tug Towing --start 2026-10-19 --pad 3 --zoom 10 --show
python plot_tracks.py --class Tanker --mmsi 368127000 --output washington.png
```

Each vessel of the given class(es) with a report in the box is drawn on an OpenStreetMap basemap, using its full
track (inside and outside the box) from `--pad` hours before its first report in the box to `--pad` hours after its
last one, for each pass. Dots mark where each track starts, arrowheads show the direction of travel, and the box is
drawn dashed. The eight vessels with the longest tracks get their own color and legend entry; any others are grey.

| Option | Meaning |
|---|---|
| `--class` | vessel class(es); required |
| `--start`, `--end`, `--box` / `--bbox` | as for `ship_summary.py` |
| `--mmsi` | only these vessels |
| `--pad` | hours of track before and after each pass (default 6) |
| `--max-gap` | minutes without a report that break a track line (default 120), so coverage gaps are not drawn as straight lines |
| `--zoom` | OSM tile zoom; the automatic choice can look blurry, a higher number is sharper but downloads more tiles |
| `--output` | PNG path (default `plots/tracks_<class>_<box>_<start>_<end>.png`; `plots/` is git-ignored) |
| `--show` | also open the map in a window |

`plot_tracks.py` needs cartopy (in `requirements.txt`). `ModuleNotFoundError: No module named 'cartopy'` means the
script ran under a Python environment that does not have the requirements installed.

### Caveats

- Only moving vessels are archived (SOG > 0.5 kn), so time spent tied up or at anchor is missing: a ship calling at a
  pier shows up as an arrival and a later departure, not a continuous stay.
- Boats tied up in a marina can report GPS jitter of 0.6 to 1 kn, which passes the moving threshold. In the Anacortes
  box this inflates the Pleasure class (many short "visits" at near-zero speed); filter with `--class` to focus on
  commercial traffic.
- The archive samples about every 15 minutes, so a fast transit of a small box may have a single report (and
  `hours_in_box` of 0), and tracks are straight lines between samples.

## Credentials

The AISHub username is read from the `AISHUB_USERNAME` environment variable (or a local `.env`, which is gitignored). In GitHub Actions it comes from the repository secret `AISHUB_USERNAME`. Never commit it.
The same applies to the AWS keys for the archive; GitHub Actions needs none (it uses the `ais-shipnoise-writer` role).

## Scheduling

GitHub often delays or drops `schedule` runs, so the workflow is started every 15 minutes by an external
scheduler (cron-job.org) that calls the GitHub API:

```
POST https://api.github.com/repos/orcasound/ais-shipnoise/actions/workflows/pages.yml/dispatches
Authorization: Bearer <fine-grained token: this repo only, Actions read & write>
Accept: application/vnd.github+json
{"ref": "main"}
```

The workflow's own `schedule` (minutes 7 and 37) remains as a backup.
