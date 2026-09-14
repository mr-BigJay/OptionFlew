# Pre-release

Experimental features on top of stable v1:

- `optionflow/market_context.py` + `enriched_feeds.py` — Binance spot/futures (funding, OI, basis, taker & long/short ratios, depth, liq sample), Fear & Greed, RSI/EMA 4h, Deribit OI/IV/P-C/max pain/gamma, news calendar
- `optionflow/structure_context.py` — ICT phase 1 (PDH/PDL premium-discount, sweeps, 4h FVG)
- Enriched report = **یک پارagraph سناریو** (spot→B→C، Taker/OI/Funding در متن، بدون لیست جدا «زمینهٔ بازار»)
- ` .venv/bin/python -m optionflow --simple --enriched` — نه `python3` سیستمی
- به‌روزرسانی VPS: `sudo bash scripts/update-dashboard-pre.sh`
- Dashboard scheduler respects `OPTIONFLOW_ENRICHED=1` in `.env`

Not recommended for production until merged to `main`.
