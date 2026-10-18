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
From Python: `ais_db.query_reports(mmsi=..., vessel_class=..., start=..., end=...)`.
Set `AIS_ARCHIVE` to a local directory to write and query a local archive instead (for testing).

Access (AWS account 648183724555):
- GitHub Actions uses the IAM role `ais-shipnoise-writer` via OIDC (no stored keys); it may only `s3:PutObject` under `ais/`,
  and only from `main` of this repo.
- The IAM user `ais-archive-reader` may only list and read under `ais/`; its keys go in your local `.env`.

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
