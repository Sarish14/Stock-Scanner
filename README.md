# F&O Pre-open Gap Scanner (NSE)

Every trading day NSE runs a pre-open call auction from 09:00 to 09:08 IST. This
tool reads that auction for **F&O stocks only** and lists the ones whose
opening price (IEP) is within a configurable % range of the previous close
(default **+1% to +2%**), with a sector filter.

Data comes from public NSE endpoints. No broker account or API key is needed.

| What | Source |
|---|---|
| Pre-open price and previous close (F&O stocks only) | `nseindia.com/api/market-data-pre-open?key=FO` |
| Sector / industry | Nifty Total Market constituents CSV (cached for 7 days in `data/`) |
| Lot size | `fo_mktlots.csv` (cached for 1 day) |

## Run

```bash
uv sync                              # once

uv run streamlit run app.py          # web UI → http://localhost:8501
uv run scan.py                       # CLI, uses config.toml
uv run scan.py --min 0.5 --max 3 --sector "Financial Services" --sector Healthcare
uv run scan.py --list-sectors        # sector names and how many stocks match
uv run scan.py --save                # also writes data/history/YYYY-MM-DD.csv
```

Defaults live in [config.toml](config.toml) (`min_pct`, `max_pct`, `sectors`).
Negative values scan for gap-downs.

## Timing

- **Before 09:00 IST:** NSE still serves the previous session's pre-open, and the app warns about it.
- **09:00–09:08 IST:** prices are indicative and change as orders come in. The app says so.
- **After about 09:08 IST:** the IEP is the opening price. NSE keeps serving this data for the rest of the day.

## Daily automatic run (cron)

This machine is set to IST. Add this with `crontab -e`:

```cron
9 9 * * 1-5  cd /home/sarish-test/Sarish/MyProject && /home/sarish-test/.local/bin/uv run scan.py --save >> data/cron.log 2>&1
```

On market holidays the script exits with code 2, because the data is not from that day.

## Deploy free on Streamlit Community Cloud

1. Create an **empty** repository on GitHub. Don't add a README or .gitignore.
2. Push this project to it:
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
3. Go to https://share.streamlit.io, sign in with GitHub, and click **Create app**.
   Pick the repo, branch `main`, and main file `app.py`. Under **Advanced settings**, choose Python **3.12**.
4. Deploy. Dependencies come from `requirements.txt`, and the theme comes from `.streamlit/config.toml`.

> **Caveat:** NSE often blocks requests from cloud data centres. If the deployed app shows
> "Could not reach NSE", run it locally instead or switch to a broker data API.
> Anything the app caches in `data/` is lost whenever the cloud app restarts. That's fine for the web app.
