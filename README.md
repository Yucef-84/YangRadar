# YangRadar

Korean stock dashboard for Kiwoom REST API data.

## Planning document

- [YangRadar Kiwoom REST implementation plan](docs/kiwoom-rest-implementation-plan.html)

## What changed

- Runtime data source is Kiwoom REST API.
- Fake OHLCV, investor flow, and program-trading sample data are not shown.
- If Kiwoom credentials are missing or an endpoint is unavailable, the UI shows a clear empty state.
- Kiwoom REST credentials can be saved from the app settings screen to a local-only `.env` file.

## Setup

You can enter Kiwoom REST credentials directly inside the app:

1. Start the backend and frontend.
2. Open the app in the browser.
3. Click `설정` in the top bar.
4. Enter `앱키`, `시크릿키`, optional `계좌번호`, then click `저장`.

The app stores credentials only in the local project `.env` file on this PC. `.env` is ignored by Git, so it is not pushed to GitHub.

You can also create `.env` manually if you prefer:

```powershell
Copy-Item .env.example .env
notepad .env
```

Required values:

```text
KIWOOM_APP_KEY=your_app_key
KIWOOM_SECRET_KEY=your_secret_key
KIWOOM_ENV=real
```

Use `KIWOOM_ENV=mock` only if the Kiwoom mock domain supports the endpoint you are testing.

## Run

Open two PowerShell windows.

Backend:

```powershell
cd C:\Users\admin\Documents\Tools\YangRadar
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
cd C:\Users\admin\Documents\Tools\YangRadar
$env:VITE_API_BASE="http://127.0.0.1:8001"
npm run dev --prefix frontend
```

Open the Vite URL, usually `http://127.0.0.1:5173`.

## API

- `GET /api/health`
- `GET /api/search?q=삼성전자`
- `GET /api/settings/kiwoom`
- `POST /api/settings/kiwoom`
- `POST /api/stocks/{code}/refresh`
- `GET /api/stocks/{code}/dashboard?lookback=180`

The dashboard response includes `data_quality`, which tells the frontend whether price, chart, investor, and program-trading data came from Kiwoom REST or are unavailable.
