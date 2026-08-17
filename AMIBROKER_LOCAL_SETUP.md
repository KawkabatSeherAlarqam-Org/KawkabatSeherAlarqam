# AmiBroker local connection

1. Open AmiBroker and the database containing `XAUUSD`.
2. Stop the old Python `http.server` on port 8080.
3. Run `C:\KawkabatSeherAlarqam\START_AMIBROKER_WHEEL.cmd`.
4. Open `http://127.0.0.1:8080/`.

Checks: `/api/health` and `/api/quote`. The wheel page and API use the same origin. Polling is 100ms and the UI becomes stale after 1.5 seconds. V481 calculations and geometry are unchanged.
