# YangRadar

키움 REST API 데이터를 이용해 국내 종목을 한 화면에서 확인하는 종목 통합 대시보드입니다.

자동매매/주문 기능은 포함하지 않습니다. 키움 REST API에서 받을 수 없는 데이터는 임의 샘플로 채우지 않고 화면에 데이터 없음 상태로 표시합니다.

## 주요 기능

- 종목명/종목코드 검색
- 일봉/주봉/월봉 차트 전환
- 캔들 차트, 거래량, MA 5/10/20/60/120
- OBV, RSI 14, 시장 ADR, 심리도 10
- 종목 설명, 시장, 업종, 테마 영역
- 외국인/기관 5일, 20일, 60일, 120일 누적 수급
- 상장주식수 대비 수급 비율
- 프로그램매매 비차익 일별 추이와 기간 누적
- 일별/주간/월간 거래대금과 거래량 회전률
- 차트 영역과 오른쪽 패널 크기 조절

## 친구에게 ZIP으로 보내는 방법

이 프로젝트는 GitHub 공개 배포보다 ZIP 파일로 전달해서 친구 PC에서 로컬 실행하는 방식이 안전합니다. 내 PC의 `.env`, 가상환경, 로그 파일은 ZIP에 넣지 않습니다.

보내는 사람은 PowerShell에서 아래 명령을 실행해 배포용 ZIP을 만듭니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\make-zip.ps1
```

완료되면 `release\YangRadar.zip` 파일이 생깁니다. 이 ZIP 파일만 이메일이나 메신저로 보내면 됩니다.

## 가장 쉬운 실행 방법

ZIP 파일을 원하는 폴더에 압축 해제하고 `Start YangRadar.cmd`를 더블클릭하세요.

먼저 PC에 Python 3.11 이상과 Node.js 20 이상이 설치되어 있어야 합니다.

첫 실행에서는 필요한 Python·Node 패키지를 자동으로 설치하므로 시간이 조금 걸릴 수 있습니다. 설치가 끝나면 백엔드와 프론트엔드를 숨김 상태로 실행하고 브라우저에서 YangRadar를 자동으로 엽니다. 다음 실행부터는 바로 시작됩니다.

종료하려면 `Stop YangRadar.cmd`를 더블클릭하세요.

브라우저가 자동으로 열리지 않으면 아래 주소를 직접 여세요.

```text
http://127.0.0.1:4173
```

앱 상단의 `설정` 버튼에서 본인의 키움 REST API 앱키와 시크릿키를 입력합니다. 입력값은 실행 중인 PC의 `.env` 파일에만 저장됩니다.

### PowerShell에서 직접 실행하기

더블클릭 대신 PowerShell을 사용하려면 프로젝트 폴더에서 다음 명령을 실행하세요.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-yangradar.ps1
```

설치 중 `python`, `node`, `npm`을 찾을 수 없다는 메시지가 나오면 Python과 Node.js를 먼저 설치한 뒤 PowerShell을 새로 열어 다시 실행합니다.

## 실행 준비

키움 REST API 키는 앱 상단의 `설정` 버튼에서 입력할 수 있습니다. 입력한 키는 이 PC의 프로젝트 폴더 `.env` 파일에만 저장되며 GitHub에는 올라가지 않습니다.

수동으로 설정하려면 `.env.example` 파일을 `.env`로 복사한 뒤 키움 REST API 정보를 입력합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

필수 값:

```text
KIWOOM_APP_KEY=키움_앱키
KIWOOM_SECRET_KEY=키움_시크릿키
KIWOOM_ACCOUNT_NO=계좌번호
KIWOOM_ENV=real
```

## 실행 방법

PowerShell 창을 2개 열고 각각 실행합니다.

### 1. 백엔드 실행

```powershell
cd C:\Users\admin\Documents\Tools\YangRadar
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

가상환경을 새로 만들었다면 필요한 패키지를 설치해야 합니다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install fastapi uvicorn requests
```

### 2. 프론트엔드 실행

```powershell
cd C:\Users\admin\Documents\Tools\YangRadar
npm.cmd run dev --prefix frontend
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:4173
```

화면이 예전 상태로 보이면 `Ctrl+F5`로 강제 새로고침하세요.

## 서버가 꼬였을 때

예전 백엔드가 계속 떠 있으면 새 코드가 반영되지 않거나 데이터가 0으로 보일 수 있습니다. 이 경우 PowerShell에서 YangRadar 관련 서버를 종료한 뒤 다시 실행합니다.

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('python.exe','node.exe') -and $_.CommandLine -match 'YangRadar|uvicorn|vite|backend.app.main' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

그 다음 백엔드와 프론트엔드를 다시 실행합니다.

## API

- `GET /api/health`
- `GET /api/search?q=삼성전자`
- `GET /api/settings/kiwoom`
- `POST /api/settings/kiwoom`
- `POST /api/settings/kiwoom/test-auth`
- `POST /api/stocks/{code}/refresh`
- `GET /api/stocks/{code}/dashboard?lookback=300&timeframe=daily`

`timeframe` 값:

- `daily`: 일봉
- `weekly`: 주봉
- `monthly`: 월봉

대시보드 응답에는 `data_quality`가 포함됩니다. 각 패널별로 키움 REST API 데이터 수신 상태를 확인할 수 있습니다.

## 데이터 기준

- 가격, OHLCV, 거래량, 거래대금은 음수 기호가 붙어 내려와도 절댓값으로 정규화합니다.
- 등락폭, 등락률, 외국인/기관 순매수, 프로그램 순매수는 부호를 유지합니다.
- 수급 비율의 분모는 유통주식수가 아니라 상장주식수입니다.
- ADR은 개별 종목 지표가 아니라 시장 상승종목수 / 하락종목수 * 100 기준입니다.
- 키움 API 오류 또는 미지원 항목은 가짜 데이터로 대체하지 않습니다.

## 참고 문서

- [YangRadar Kiwoom REST 구현 계획](docs/kiwoom-rest-implementation-plan.html)
