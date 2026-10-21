API 응답 샘플. Android `core`와 iOS `MixnavutsKit` 테스트가 같은 파일을 읽어서, 두 앱이 같은 API 계약을 따르는지 확인한다.

다시 만들기:

```bash
python -m mixnavuts route 서부터미널 동부산업단지 --json   # 형식 확인용 (출발 시각은 오늘 08:10)
```

`routes_response.json`은 2026-10-21 08:10 KST 출발, 합성 교통 시드 1로 만들었다 (tests/test_api.py의 `DEPART`).
