# 한국 실데이터·지도 연동

엔진이 실제 도로망과 실시간 교통으로 경로를 찾고, 앱이 국내 지도 위에 보여 주기 위한 설정이다. 외부 서비스 키는 **엔진 서버에만** 두고 앱에는 넣지 않는다. 지도 SDK 키는 앱에 들어가는 공개 키라서 예외다.

## 한눈에

| 용도 | 서비스 | 쓰는 곳 | 키 위치 | 검증 상태 |
| --- | --- | --- | --- | --- |
| 실시간 구간 속도 | 국가교통정보센터(ITS) 교통소통정보 | `mixnavuts/korea/its.py` | 서버 환경 변수 `ITS_API_KEY` | 공개 응답 형식으로 만든 테스트 데이터만. 실제 키로는 미확인 |
| 사고·공사·통제 | ITS 돌발상황정보 | 같음 | 같음 | 같음 |
| 도로망 | 국가표준노드링크 | `mixnavuts/korea/nodelink.py` | — | 직접 만든 shapefile로 테스트. 실제 배포 파일의 필드명은 확인 필요 |
| 좌표 변환 | EPSG 5179·5181·5185~5188 | `mixnavuts/korea/tm.py` | — | pyproj와 비교해 한국 전역 오차 7 cm 이하 |
| 목적지 검색 | 카카오 로컬 API | `mixnavuts/korea/kakao.py` | 서버 환경 변수 `KAKAO_REST_API_KEY` | 공개 응답 형식 테스트만 |
| 지도 표시 (Android) | 네이버 지도 SDK | `android/app/.../ui/map` | `android/local.properties` | 빌드 미확인 |
| 지도 표시 (iOS) | 네이버 지도 SDK(SPM), 없으면 Apple MapKit | `ios/Mixnavuts/Views` | `ios/Config/Local.xcconfig` | 빌드 미확인 |

이 저장소를 만든 환경에서는 위 서비스에 접속할 수 없었다. 그래서 연동 코드는 공개 문서의 형식대로 만든 응답으로만 테스트했다. 실제 키를 넣은 뒤 아래 "처음 확인할 것"부터 점검한다.

## 1. 국가표준노드링크 (도로망)

1. ITS 국가교통정보센터 사이트의 표준노드링크 자료실에서 최신 전국 파일을 받는다.
2. 압축을 풀면 `MOCT_NODE.shp`와 `MOCT_LINK.shp`가 있다. `.dbf`, `.shx`, `.prj`도 같은 폴더에 둔다.
3. 필드와 좌표계를 확인한다.

   ```bash
   pip install "mixnavuts[korea]"        # pyshp (shapefile 읽기)
   python -m mixnavuts nodelink-info ~/data/nodelink
   ```

   로더는 다음 필드를 쓴다.
   - 노드: `NODE_ID`, `NODE_NAME`
   - 링크: `LINK_ID`, `F_NODE`, `T_NODE`, `ROAD_RANK`, `ROAD_NAME`, `ROAD_NO`, `MAX_SPD`, `LENGTH`, `CONNECT`

   이름이 다르면 `nodelink.py`의 `_text(...)` 호출을 고친다. 좌표계는 `.prj`를 보고 `--epsg`로 넘긴다(기본 5186).
4. 범위를 정해 서버를 띄운다. 순수 Python이라 전국은 무겁다. 수도권 정도로 시작한다.

   ```bash
   python -m mixnavuts serve --network nodelink --nodelink ~/data/nodelink \
       --bbox 126.76,37.41,127.18,37.70
   ```

도로 등급은 `ROAD_RANK`로 나눈다. 101 고속국도 → 고속도로, 102 도시고속국도와 103 일반국도 → 국도급, 104 → 간선, 105·106 → 보조간선, 107·108 → 이면도로다. `CONNECT`가 연결로이면 IC·JC 램프로 본다. 굴곡도는 링크 형상에서 계산하므로 실제 와인딩 도로를 그대로 찾는다.

**통행료는 근사값이다.** 고속도로 링크 길이 × 44.3원/km로 계산한다. 폐쇄식 고속도로 요금은 진입·진출 영업소 쌍으로 정해지므로, 정확한 값은 한국도로공사 영업소 간 요금 자료를 붙여야 나온다(아래 "다음 단계").

## 2. ITS 실시간 교통·돌발 정보

1. ITS 국가교통정보센터의 오픈 API에서 인증키를 신청한다. 교통소통정보와 돌발상황정보를 쓴다.
2. 키를 서버 환경 변수로 넣고 실행한다.

   ```bash
   export ITS_API_KEY=발급받은_키
   python -m mixnavuts serve --network nodelink --nodelink ~/data/nodelink --bbox 126.76,37.41,127.18,37.70
   curl localhost:8080/v1/health     # live.source가 "its", observed_links > 0 인지 확인
   ```

동작 방식은 이렇다.

- **갱신**: 요청이 들어올 때, 마지막 조회 후 5분이 지났으면 다시 가져온다. ITS 갱신 주기에 맞춘 값이다. 조회가 실패하면 직전 데이터를 계속 쓴다.
- **링크 연결**: 속도는 `linkId`(표준링크ID)로 링크에 바로 붙는다. 속도 0은 "데이터 없음"으로 본다.
- **돌발상황 반영**: 종류별로 그 링크의 속도 상한을 정한다. 통제 0, 사고 0.3, 공사·고장 0.5, 기상 0.7. 종료 시각이 없으면 1시간 뒤(최소 지금부터 15분)를 해소 예상 시각으로 잡는다. 표는 `its.py`의 `EVENT_SPEED_FACTOR`다.

### 지금 바로: 속도 아카이브

ETA 백테스트와 "시간대별 평소 속도" 학습에는 과거 데이터가 필요하다. 서버 한 대에서 계속 돌려 둔다.

```bash
ITS_API_KEY=… python -m mixnavuts archive --bbox 126.76,37.41,127.18,37.70 --db its.sqlite
python -m mixnavuts serve --network nodelink --nodelink ~/data/nodelink --bbox … --archive its.sqlite
```

`--archive`를 주면 링크별·15분 단위로 평일 중앙값 속도를 평소 패턴으로 쓴다. 데이터가 없는 링크는 도로 등급별 기본 패턴을 쓴다.

## 3. 카카오 로컬 (목적지 검색)

1. Kakao Developers에서 애플리케이션을 만들고 REST API 키를 받는다. 콘솔에서 로컬(카카오맵) API 사용 설정이 필요할 수 있다.
2. `export KAKAO_REST_API_KEY=…` 후 `serve`. `/v1/health`의 `search`가 `kakao`가 된다.

검색 결과는 좌표로 경로를 요청한다. 앱이 위치를 알면 가까운 순으로 정렬한다.

## 4. 네이버 지도 (앱 지도 표시)

네이버 클라우드 플랫폼 콘솔의 Maps에서 Application을 등록한다. Mobile Dynamic Map을 선택하고 아래 두 식별자를 넣는다.

- Android 패키지 이름 `com.mixnavuts.app`
- iOS Bundle ID `com.mixnavuts.app`

**Android**: `android/local.properties`

```properties
naver.map.clientId=발급받은_ID
mixnavuts.api=http://192.168.0.10:8080
```

**iOS**: `ios/Config/Local.xcconfig` (git에 올라가지 않는다)

```
NAVER_MAP_CLIENT_ID = 발급받은_ID
MIXNAVUTS_API_URL = http:/$()/192.168.0.10:8080
```

키가 없으면 Android는 경로선만 그리는 기본 화면을 쓰고, iOS는 Apple MapKit을 쓴다. 차량 화면은 키와 상관없이 따로 그린다.

- Android Auto: 지도 SDK를 차량 화면(Surface)에 띄울 수 없어 앱이 직접 그린다.
- CarPlay: MapKit을 쓴다.

**SDK 버전과 인증 방식은 처음 빌드할 때 확인한다.** 2025년 네이버 클라우드 Maps 개편 뒤 새로 발급하는 키는 새 인증 방식을 쓴다(Android `NcpKeyClient`, iOS `ncpKeyId`). 그 경우 두 가지를 바꾼다.

- SDK 버전: `android/gradle/libs.versions.toml`의 `naver-map`, `ios/project.yml`의 `NMapsMap`
- 인증 코드: `NaverMapSetup`(Android `NaverRouteMap.kt`, iOS `NaverRouteMapView.swift`)

## 처음 확인할 것 (실제 키를 넣은 뒤)

1. `nodelink-info` 출력의 필드명이 로더와 같은지.
2. `/v1/health`에서 `live.observed_links`가 0보다 큰지. 0이면 링크 ID 형식을 확인한다. ITS 응답의 `linkId`와 표준노드링크 `LINK_ID`의 자릿수·문자열 형태가 같아야 한다.
3. `its.py`의 `_items` / `traffic` / `events`가 실제 응답 필드명(`linkId`, `speed`, `createdDate`, `eventType`, `startDate`, `endDate`)과 맞는지.
4. 카카오 검색 결과가 `/v1/search`로 나오는지.
5. 네이버 지도가 앱에서 뜨는지, 인증 오류(401)가 없는지.

## 다음 단계

- **통행료**: 한국도로공사 공공데이터의 영업소 간 통행요금을 붙인다. 고속도로 진입·진출 영업소 쌍으로 계산하고, 휴게소 정보도 같은 곳에서 가져온다.
- **회전 제한·회전 비용**: 표준노드링크의 회전 정보를 쓰는 링크 기반(edge-based) 그래프로 바꾼다. 도심 ETA 오차의 큰 원인이다.
- **지자체 소통 정보**: 서울 TOPIS 등을 추가한다. ITS와 링크 체계가 다르면 매칭이 필요하다.
- **성능**: 전국 규모 탐색에는 Contraction Hierarchies 같은 전처리, 또는 핵심 탐색의 Rust·C++ 이식이 필요하다.
