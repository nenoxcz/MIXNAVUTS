# MIXNAVUTS (믹스네브츠)

**Predictive Multi-Route Navigation** — 수백 개의 후보 경로를 내부적으로 검토하고, 실제로 가장 빨리 도착할 경로를 골라 3~5개만 제시하는 내비게이션.

> 수백 개의 경로를 탐색하는 능력보다, 그중 어떤 경로가 **실제로 가장 빨리 도착하는지 정확하게 판단하는 능력**이 더 중요하다.

전체 구상(교통 데이터, Android Auto·CarPlay, HUD, 로드맵)은 [docs/CONCEPT.md](docs/CONCEPT.md)에 있다.

## 구성

```
mixnavuts/          MIXNAVUTS Engine (Python): 경로 탐색 · 교통 예측 · ETA · 차로 안내 · 자체 지도 타일 · HTTP API
  korea/            국가 데이터: 표준노드링크 · 정밀도로지도 · 단속카메라 · ITS · 브이월드 · 도로명주소 · 좌표계
android/            Android 앱
  core/             플랫폼 독립 Kotlin: API 클라이언트 · 경로 추적 · 재탐색 · HUD 상태(차로·경고) · 시뮬레이터
  app/              휴대폰 화면(Compose) · MapLibre 지도 · Android Auto(차로 안내) · 계기판(cluster)
ios/                iOS 앱
  MixnavutsKit/     Swift 패키지: android/core와 같은 로직
  Mixnavuts/        휴대폰 화면(SwiftUI) · MapLibre 지도(없으면 MapKit) · CarPlay
shared/fixtures/    API 응답 샘플 (세 플랫폼 테스트가 공유)
docs/               구상 · API 명세 · 한국 데이터 연동
```

상용 지도 SDK 없이, 국가 공개 데이터로 경로·차로 안내·지도 타일·검색을 모두 엔진의 자체 API로 제공한다([docs/KOREA.md](docs/KOREA.md)). 앱은 이 API만 호출하고([docs/API.md](docs/API.md)) 지도는 오픈소스 MapLibre로 그린다. 외부 키(ITS, 브이월드, 도로명주소)는 서버에만 둔다. 휴대폰 화면은 디자인을 입히기 전의 최소 레이아웃이다. 안내 내용(HUD 상태, 문구, 거리·시간 형식)은 코어가 정하고, 화면 파일은 배치만 한다.

## 현재 상태

| 영역 | 있음 | 검증 |
| --- | --- | --- |
| 엔진 | 후보 생성, 시간 의존 ETA, 선호·다양성 선택, 백테스트, 턴바이턴·차로 안내, 경로 경고, HTTP API | Python 테스트 73개 |
| 자체 지도 API | 도로망 벡터 타일(MVT), MapLibre 스타일, 브이월드 배경지도 중계 | 타일은 표준 디코더(mapbox-vector-tile)와 대조 |
| 국가 데이터 | 표준노드링크, 정밀도로지도(차로·신호등·과속방지턱), 경찰청 단속카메라, ITS 교통·돌발, 브이월드·도로명주소 검색, 좌표계 자동 인식, ITS 아카이브 | 공개 형식대로 만든 데이터로 테스트. 좌표 변환은 pyproj와 비교. 실제 파일·키로는 미확인 |
| Android core | 경로 추적, 이탈 판정, 재탐색, HUD(차로·경고), 시뮬레이터 | JUnit 18개 (JVM, Kotlin 2.2) |
| Android app | Compose 화면, MapLibre 지도, Android Auto(목적지·미리보기·안내·차로), `updateTrip`으로 계기판·HUD 전달, 차량 속도, 계기판 세션 | **빌드 미확인** (이 환경에서 Google Maven 차단). 문법 검사(ktlint)만 |
| iOS | MixnavutsKit, SwiftUI 화면, MapLibre/MapKit, CarPlay 안내 | **빌드 미확인** (Xcode 없음). 문법 검사(tree-sitter)만. Kit 테스트는 작성만 |

아직 없는 것: 교차로 회전 비용, 정확한 폐쇄식 통행료, 지도 한글 라벨(글꼴 서빙), 다수 차량 분배, 디자인.

## 빠른 시작

### 엔진

Python 3.11 이상. 합성 도시는 외부 의존성 없이 돌아간다.

```bash
python -m mixnavuts serve                                        # API 서버 (합성 도시) → http://localhost:8080/v1/health
python -m mixnavuts route 서부터미널 동부산업단지 --depart 08:10     # 터미널에서 바로 보기 (--json: API 응답)
python -m mixnavuts route 북부캠퍼스 북동리조트 --depart 17:40 --mode scenic
python -m mixnavuts backtest                                     # ETA 예측 전략 비교
python -m unittest discover -s tests
```

```
MIXNAVUTS · 서부터미널 → 동부산업단지 · 출발 08:10 · 모드 balanced
후보 224개 (via 214, penalty 10, fastest 1, highway 1, …) → 시간 의존 ETA 평가 → 4개 제시
반영된 돌발상황 1건

[1] 추천 · 무료도로
    도착 08:40  소요 30분 15초 (+3분)  ·  25.2 km  ·  통행료 0원  ·  고속도로 0%
    남북대로 0 → 국도 7호선
[2] 최단시간 · 고속도로
    도착 08:37  소요 27분 15초  ·  22.1 km  ·  통행료 1,860원  ·  고속도로 84%
    중앙고속도로 → 동서대로 14
...
```

국가 데이터(표준노드링크·정밀도로지도·단속카메라·ITS·브이월드)로 띄우는 방법은 [docs/KOREA.md](docs/KOREA.md)에 있다.

```bash
pip install "mixnavuts[korea]"
ITS_API_KEY=… VWORLD_API_KEY=… python -m mixnavuts serve --network nodelink \
    --nodelink ~/data/nodelink --hdmap ~/data/hdmap --cameras ~/data/cameras.csv \
    --bbox 126.76,37.41,127.18,37.70
```

지도는 `http://localhost:8080/v1/style.json`을 MapLibre(웹·Android·iOS)에 넣으면 바로 보인다.

### Android

Android Studio로 `android/`를 연다. 에뮬레이터는 PC의 엔진(`http://10.0.2.2:8080`)에 붙는다.

- **설정**: 실기기에서 쓸 엔진 주소는 `android/local.properties`에 넣는다(`mixnavuts.api=…`). 지도는 엔진의 `/v1/style.json`을 MapLibre로 그린다.
- **코어 테스트**: `./gradlew :core:test`
- **Android Auto**: Desktop Head Unit(DHU)으로 확인한다.
  1. 휴대폰 Android Auto 설정에서 개발자 모드를 켜고 "알 수 없는 출처"를 허용한다.
  2. DHU를 연결하고 목적지 → 경로 미리보기 → 안내 시작 순으로 확인한다.
  3. 실제로 운전하지 않아도 된다. 휴대폰의 시뮬레이션 주행이나 호스트의 자동 주행(auto drive)으로 경로를 따라간다.

### iOS

```bash
brew install xcodegen
cd ios && xcodegen generate && open Mixnavuts.xcodeproj
```

- **설정**: 엔진 주소는 `ios/Config/Local.xcconfig`에 넣는다(형식은 `Config/Mixnavuts.xcconfig` 참고). 지도는 MapLibre 패키지로 엔진의 `/v1/style.json`을 그린다. 패키지를 빼면 MapKit을 쓴다.
- **Kit 테스트**: `cd ios/MixnavutsKit && swift test`
- **CarPlay**: Xcode 시뮬레이터의 I/O → External Displays → CarPlay에서 확인한다. 실기기에서 쓰려면 Apple에 CarPlay 내비게이션 앱 권한을 신청해야 한다.

## 엔진 파이프라인

```
출발지·도착지·출발 시각
  │
  ├─ 1. 기본 경로      시간 의존 최단시간(TD-Dijkstra) + 비용 프로파일 6종
  │                    (최단거리, 고속도로 우선/회피, 무료도로, 간선 위주, 와인딩)
  ├─ 2. 대안 경로      페널티 방식: 찾은 경로의 링크 비용을 올리고 다시 탐색
  ├─ 3. 후보 확대      via-node 방식: 순방향·역방향 트리 두 번의 탐색으로
  │                    노드 v마다 s→v→t 경로 → 중복·루프 제거 → 수백 개
  ├─ 4. ETA 평가       모든 후보를 출발 시각부터 링크 단위로 "주행"
  │                    (진입 시각의 예측 속도로 적분)
  └─ 5. 선택           개인 선호 비용으로 정렬, 겹침 ≤ 70% 조건으로 3~5개
                       (최단시간 경로는 항상 포함, 라벨 부여)
```

- **후보 생성은 빠르게, 평가는 정확하게.** 생성 단계는 정적 가중치를 쓴다. 다만 각 링크를 "최단시간 경로가 그 링크에 도달하는 시각"의 속도로 잰다. 정확한 ETA는 4단계에서 시간 의존 모델로 다시 계산한다.
- **FIFO 보장.** 속도를 구간별 상수로 두고 거리를 적분해 통행시간을 구한다. 그래서 늦게 진입한 차량이 먼저 빠져나오는 일이 없고, 시간 의존 Dijkstra가 정확해진다. 진입 시각의 속도만 읽는 단순한 방식은 이 성질이 깨진다.

### 교통 예측 모델 (`mixnavuts/traffic.py`)

| 모델 | 내용 |
| --- | --- |
| `ProfileTraffic` | 링크별·시간대별(15분) 평소 속도 |
| `SnapshotTraffic` | 출발 시점의 속도가 끝까지 유지된다고 가정 (단순 "현재 교통" ETA) |
| `PredictiveTraffic` | 지금 관측된 편차(관측/평소)가 시간상수 τ(기본 40분)로 평소 패턴에 수렴. 돌발상황은 해소 예상 시각까지 속도 상한을 적용하고, 이후에는 평소 패턴으로 돌아감 |

### ETA 백테스트 (`python -m mixnavuts backtest`)

엔진은 **출발 시점에 알 수 있는 정보만**(평소 패턴, 관측 링크 속도, 돌발 보고) 사용해 경로를 고르고 도착 시각을 예측한다. 고른 경로를 그날의 "실제" 교통으로 주행해 보고, 실제 최적 경로(실제 교통에서 구한 시간 의존 최단시간)와 비교한다.

```
전략                         MAE     P90    편향    MAPE  적중률    손실  후보풀
                            (분)    (분)    (분)     (%)     (%)    (분)    (분)
historical                  0.90    1.73   -0.66     4.5      85    0.45    0.08
live_snapshot               0.70    1.46   -0.20     3.4      95    0.25    0.06
live+history                0.51    1.14   -0.29     2.6      95    0.23    0.05
live+history+incidents      0.49    1.13   -0.26     2.5      97    0.22    0.05
```

- **적중률**: 실제로 가장 빨리 도착하는 경로를 골랐는가. 이 프로젝트의 핵심 지표다.
- **손실**: 고른 경로가 실제 최적보다 몇 분 늦었는가.
- **후보풀**: 후보 중 가장 좋은 경로가 실제 최적보다 몇 분 늦은가. 0에 가까우면 좋은 경로를 놓치지 않고 있다는 뜻이다.

위 결과는 평균 19분짜리 합성 주행 60회에서 나왔다. 합성 데이터의 가정(편차의 지속성, 돌발 빈도)이 결과를 좌우하므로 **실제 데이터로 다시 측정해야 의미가 있다.** 실제 데이터에서는 아카이브된 링크 속도를 시간순으로 재생해 "실제 교통"으로 쓰면 된다. 그러면 직접 주행하지 않아도 같은 백테스트를 돌릴 수 있다.

## 엔진 코드

| 파일 | 구상의 모듈 | 내용 |
| --- | --- | --- |
| `mixnavuts/graph.py` | — | 방향 그래프 도로망, 도로 등급, 통행료, 굴곡도, 원본 링크 ID |
| `mixnavuts/search.py` | Route | Dijkstra, 시간 의존 최단시간 탐색 |
| `mixnavuts/candidates.py` | Route | 후보 경로 생성 (프로파일·페널티·via-node) |
| `mixnavuts/traffic.py` | Traffic | 평소·스냅샷·예측 교통 모델, 돌발상황 |
| `mixnavuts/live.py` | Traffic | 실시간 피드 인터페이스 (합성, ITS) |
| `mixnavuts/evaluate.py` | Route | 시간 의존 ETA, 거리·통행료·고속도로 비율·굴곡도, 경로 겹침 |
| `mixnavuts/ranking.py` | Personal | 주행 목적별 비용, 다양성 있는 3~5개 선택과 라벨 |
| `mixnavuts/guidance.py` | Navigation | 턴바이턴 안내 문구, 굽은 구간(페이스노트), 링크별 예측 시각 |
| `mixnavuts/network.py` | — | 실제 좌표에 놓인 도로망, 가까운 노드 찾기 |
| `mixnavuts/api.py` | — | HTTP API |
| `mixnavuts/roadinfo.py` | Navigation | 링크별 차로 수, 차로 추천, 경로 경고(카메라·신호등·과속방지턱) |
| `mixnavuts/tiles.py`, `mapstyle.py` | — | 벡터 타일(MVT) 인코더, MapLibre 스타일 |
| `mixnavuts/korea/` | Traffic·Connect | 표준노드링크, 정밀도로지도, 단속카메라, ITS, 브이월드, 도로명주소, 카카오, 좌표계, 아카이브 |
| `mixnavuts/backtest.py` | — | ETA 정확도·최적 경로 적중률 검증 |
| `mixnavuts/synthetic.py` | — | 합성 도시 (격자 도로, 고속도로 2개·JC, 국도, 산악도로). 지도에서 가짜임이 드러나도록 인천 앞바다에 놓았다 |
| `mixnavuts/cli.py` | — | `serve`, `route`, `archive`, `backtest`, `places`, `nodelink-info`, `hdmap-info` |

Distribution(다수 차량 분배)은 아직 구현하지 않았다. 순서와 이유는 [docs/CONCEPT.md](docs/CONCEPT.md#로드맵)에 있다.
