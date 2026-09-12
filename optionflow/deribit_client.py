from __future__ import annotations

import time
from typing import Any

import httpx

DERIBIT_PUBLIC = "https://www.deribit.com/api/v2/public"


class DeribitClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._http = httpx.Client(base_url=DERIBIT_PUBLIC, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DeribitClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_index_price(self, index_name: str = "btc_usd") -> float:
        r = self._http.get(
            "/get_index_price",
            params={"index_name": index_name},
        )
        r.raise_for_status()
        return float(r.json()["result"]["index_price"])

    def fetch_option_trades(
        self,
        *,
        start_ms: int,
        end_ms: int,
        max_trades: int = 100_000,
    ) -> list[dict[str, Any]]:
        trades: list[dict[str, Any]] = []
        cursor_end = end_ms
        while len(trades) < max_trades:
            r = self._http.get(
                "/get_last_trades_by_currency",
                params={
                    "currency": "BTC",
                    "kind": "option",
                    "start_timestamp": start_ms,
                    "end_timestamp": cursor_end,
                    "count": 1000,
                    "include_old": True,
                    "sorting": "desc",
                },
            )
            r.raise_for_status()
            payload = r.json()["result"]
            batch = payload.get("trades") or []
            if not batch:
                break
            trades.extend(batch)
            if not payload.get("has_more"):
                break
            cursor_end = batch[-1]["timestamp"] - 1
            if cursor_end <= start_ms:
                break
        return trades[:max_trades]

    @staticmethod
    def window_ms(hours: float) -> tuple[int, int]:
        end = int(time.time() * 1000)
        start = end - int(hours * 3600 * 1000)
        return start, end
