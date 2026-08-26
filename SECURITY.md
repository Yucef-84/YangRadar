# YangRadar 보안 안내

YangRadar는 기본 설정에서 백엔드와 프론트엔드를 `127.0.0.1`에만 바인딩하는 로컬 앱입니다.

## 키 관리

- 키움 앱키, 시크릿키, 계좌번호는 `.env`에만 저장합니다.
- `.env`와 `.env.*` 변형(단, `.env.example` 제외), 데이터베이스 파일은 저장소에 커밋하지 않습니다.
- 키가 로그, 스크린샷 또는 커밋 이력에 노출되면 즉시 키움에서 폐기하고 재발급합니다.
- 설정 조회·저장·인증 테스트 endpoint는 loopback 요청만 허용하고, API 응답의 계좌번호는 마스킹합니다.
- `KIWOOM_BASE_URL`은 실전/모의 환경에 대응하는 Kiwoom 공식 호스트로 제한합니다.
- 공개 인터넷에 백엔드를 노출하려면 인증, TLS, 방화벽, 접근 제어를 별도로 구성해야 합니다.

설정 endpoint의 loopback 보호는 로컬 앱에서의 기본 안전장치입니다. reverse proxy나 외부 호스트에 공개할 때는 별도의 관리자 인증·TLS·방화벽을 추가해야 하며, CORS 설정만으로 endpoint가 보호된다고 간주하면 안 됩니다.

## 배포 ZIP 안전장치

- `scripts/make-zip.ps1`은 Git이 추적하는 파일만 배포 ZIP에 복사하며, 로컬의 untracked 파일은 이름이나 위치와 관계없이 포함하지 않습니다.
- `.env` 변형(안전한 템플릿인 `.env.example` 제외), SQLite/WAL/SHM 데이터베이스, 로그·PID, 인증서·개인키 계열 파일이 Git에 추적된 상태라면 ZIP 생성을 중단합니다.
- 공개 배포에는 실제 키가 없는 `.env.example`만 포함합니다. ZIP을 만들기 전에 `git ls-files`와 ZIP 내부 파일 목록을 확인하세요.

## 공개 전 점검

```powershell
git ls-files .env
git grep -n -I -E "(sk-|ghp_|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)" $(git rev-list --all)
npm.cmd audit --prefix frontend --omit=dev
pip-audit -r backend/requirements.txt
```

취약점을 발견하면 재현 단계와 영향을 포함해 저장소 관리자에게 비공개로 알려주세요. 키나 개인정보가 포함된 파일은 이슈에 첨부하지 않습니다.
