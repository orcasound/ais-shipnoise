# ais-shipnoise

Fetches current AIS positions of Salish Sea whale watch boats from [AISHub](https://www.aishub.net/) and plots them on an OpenStreetMap basemap.

Live pages (rebuilt every ~30 min by GitHub Actions):
- Whale watch boats: https://orcasound.github.io/ais-shipnoise/whale-watch.html
- Moving vessels near each hydrophone node: https://orcasound.github.io/ais-shipnoise/hydrophones.html

Each run makes a single AISHub area request (`build_site.py`) that feeds both pages, keeping well under AISHub's rate limit.
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
