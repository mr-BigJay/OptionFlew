# Pre-release

Experimental features on top of stable v1:

- `optionflow/market_context.py` — Binance funding/OI/liquidations, Deribit gamma & max pain, news calendar
- `python3 -m optionflow --simple --enriched`
- Dashboard scheduler respects `OPTIONFLOW_ENRICHED=1` in `.env`

Not recommended for production until merged to `main`.
