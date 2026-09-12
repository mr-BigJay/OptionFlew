# Pre-release

Experimental features on top of stable v1:

- `optionflow/market_context.py` — Binance funding/OI/liquidations, Deribit gamma & max pain, news calendar
- `optionflow/structure_context.py` — dev SMC phase 1: PDH/PDL premium-discount, liquidity sweeps, 4h FVG near spot
- `python3 -m optionflow --simple --enriched`
- Dashboard scheduler respects `OPTIONFLOW_ENRICHED=1` in `.env`

Not recommended for production until merged to `main`.
