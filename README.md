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

## Credentials

The AISHub username is read from the `AISHUB_USERNAME` environment variable (or a local `.env`, which is gitignored). In GitHub Actions it comes from the repository secret `AISHUB_USERNAME`. Never commit it.

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
