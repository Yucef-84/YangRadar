# YangRadar 보안 안내

YangRadar는 기본 설정에서 백엔드와 프론트엔드를 `127.0.0.1`에만 바인딩하는 로컬 앱입니다.

## 키 관리

- 키움 앱키, 시크릿키, 계좌번호는 `.env`에만 저장합니다.
- `.env`와 `data/*.sqlite3`는 저장소에 커밋하지 않습니다.
- 키가 로그, 스크린샷 또는 커밋 이력에 노출되면 즉시 키움에서 폐기하고 재발급합니다.
- 공개 인터넷에 백엔드를 노출하려면 인증, TLS, 방화벽, 접근 제어를 별도로 구성해야 합니다.

## 공개 전 점검

```powershell
git ls-files .env
git grep -n -I -E "(sk-|ghp_|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)" $(git rev-list --all)
npm.cmd audit --prefix frontend --omit=dev
pip-audit -r backend/requirements.txt
```

취약점을 발견하면 재현 단계와 영향을 포함해 저장소 관리자에게 비공개로 알려주세요. 키나 개인정보가 포함된 파일은 이슈에 첨부하지 않습니다.
