# MIXNAVUTS Engine API (v1)

엔진 서버(`python -m mixnavuts serve`)와 앱(Android `core`, iOS `MixnavutsKit`) 사이의 계약이다. JSON, UTF-8, 시각은 모두 epoch 초(UTC)다. 경로·지도·검색 모두 이 API 하나로 제공하고, 외부 키(ITS, 브이월드, 도로명주소)는 서버에만 둔다.

응답 예시는 [`shared/fixtures/`](../shared/fixtures)에 있고, 두 앱의 테스트가 같은 파일을 읽는다. 형식을 바꾸면 샘플을 다시 만들고 세 곳의 테스트(Python, Kotlin, Swift)를 모두 돌린다.

## GET /v1/health

```json
{"status": "ok", "api_version": 1, "network": "synthetic", "synthetic": true,
 "nodes": 825, "edges": 3140,
 "live": {"source": "synthetic", "as_of": 1792537800.0, "observed_links": 1452},
 "search": "network"}
```

- `live.source`: `synthetic`(합성 교통), `its`(국가교통정보센터), `none`
- `search`: `vworld`(브이월드), `juso`(도로명주소), `kakao`(카카오 로컬, 선택), `network`(도로망의 이름 있는 노드)
- `basemap`: 브이월드 배경지도를 중계하면 그 이름, 없으면 `null`

## GET /v1/places

도로망의 이름 있는 장소. 합성 도시에서는 7곳이고, 표준노드링크에서는 교차로 이름이다(최대 500개).

```json
{"synthetic": true, "places": [{"name": "서부터미널", "lat": 37.281838, "lon": 126.05}]}
```

## GET /v1/search?q=…[&lat=…&lon=…]

목적지 검색. `lat`/`lon`을 주면 가까운 순으로 정렬한다.

```json
{"provider": "vworld", "results": [
  {"name": "서울특별시청", "lat": 37.5663, "lon": 126.9779,
   "address": "서울특별시 중구 세종대로 110", "category": "", "source": "vworld"}]}
```

`source`가 `network`인 장소는 이름으로, 나머지는 좌표로 경로를 요청한다(`Place.toEndpoint()` / `Place.endpoint`).

## POST /v1/routes

```json
{"origin": {"place": "서부터미널"},
 "destination": {"lat": 37.2944, "lon": 126.2634},
 "depart": 1792537800,
 "mode": "balanced",
 "k": 4}
```

| 필드 | 내용 |
| --- | --- |
| `origin`, `destination` | `{"place": 이름}` 또는 `{"lat", "lon"}`. 좌표는 5 km 안의 가장 가까운 도로 노드에 맞춘다 |
| `depart` | 출발 시각(epoch 초). 없으면 지금 |
| `mode` | `balanced` 추천 · `fastest` 최단시간 · `economy` 통행료·거리 회피 · `highway` 고속도로 우선 · `scenic` 와인딩 |
| `k` | 제시할 경로 수, 1~5. 재탐색은 1 |

응답:

```json
{"synthetic": true, "network": "synthetic", "mode": "balanced", "depart": 1792537800.0,
 "candidates": 224, "candidate_sources": {"via": 214, "penalty": 10, "fastest": 1, "...": 1},
 "live": {"source": "synthetic", "as_of": 1792537800.0, "incidents": 1},
 "routes": [ROUTE, ...]}
```

`routes`는 추천 순이다. 가장 빨리 도착하는 경로는 항상 들어 있다.

### ROUTE

```json
{"id": "a1c3de8ddd0e",
 "labels": ["최단시간", "고속도로"],
 "depart": 1792537800.0, "arrival": 1792539434.6, "duration_s": 1634.6,
 "distance_m": 22104.2, "toll_krw": 1860, "highway_share": 0.84, "winding": 0.0,
 "summary": "중앙고속도로 → 동서대로 14",
 "geometry": [[37.281838, 126.05, 0.0], [37.288133, 126.05, 734.3], "..."],
 "segments": [{"start_index": 0, "end_index": 1, "length_m": 734.3, "speed_limit_kmh": 60,
               "road_name": "남북대로 0", "road_class": "primary", "curvature": 0.0, "toll_krw": 0,
               "offset_s": 0.0, "duration_s": 44.0, "link_id": null}],
 "maneuvers": [{"point_index": 1, "distance_m": 734.3, "type": "ramp_on", "modifier": "right",
                "road_name": "중앙고속도로 IC", "instruction": "오른쪽 중앙고속도로 진입로",
                "lanes": {"count": 3, "recommended": [3]}}],
 "alerts": [{"type": "speed_camera", "distance_m": 2279.3, "speed_limit_kmh": 100,
             "label": "과속 단속 100", "note": null}],
 "curves": [{"start_m": 0.0, "end_m": 17479.4, "direction": "right", "severity": 0.809}]}
```

| 필드 | 내용 |
| --- | --- |
| `labels` | `추천` `최단시간` `최단거리` `무료도로` `고속도로` `와인딩` `익숙한 길` `대안` |
| `geometry` | 꼭짓점마다 `[위도, 경도, 출발점부터 경로를 따라 잰 거리(m)]`. 링크 형상이 있으면 형상점까지 포함한다 |
| `segments` | 링크(도로 구간)마다 하나. `geometry[start_index..end_index]`를 덮는다. `offset_s`·`duration_s`는 출발 시각 기준 예측 진입 시각과 통과 시간이고, 남은 시간과 ETA는 이 값으로 계산한다. `link_id`는 표준링크ID(합성 도시는 `null`) |
| `maneuvers` | 처음은 `depart`, 끝은 `arrive`. `type`: `depart` `turn` `continue` `ramp_on` `ramp_off` `fork` `arrive`. `modifier`: `straight` `slight_left` `left` `sharp_left` `uturn` `slight_right` `right` `sharp_right` |
| `maneuvers[].lanes` | 있으면 써야 할 차로. `count`는 차로 수, `recommended`는 1 = 1차로(가장 왼쪽). 정밀도로지도의 차로 연결로 계산하고, 없으면 차로 수와 회전 방향으로 정한다. 모든 차로가 되거나 1차로뿐이면 생략한다 |
| `alerts` | 경로 위의 `speed_camera` `signal_camera` `section_camera` `traffic_light` `speed_bump`, 출발점부터의 거리 순. `note`는 단속카메라 설치장소 |
| `curves` | 굽은 구간(랠리식 페이스노트). `direction`: `left` `right` `mixed`, `severity` 0~1 |

## 지도 (자체 지도 API)

| 경로 | 응답 |
| --- | --- |
| `GET /v1/style.json` | MapLibre 스타일(version 8). 타일 주소는 요청한 호스트 기준으로 채운다(`X-Forwarded-Host`/`-Proto` 반영) |
| `GET /v1/tiles/{z}/{x}/{y}.mvt` | `application/vnd.mapbox-vector-tile`. 레이어 `roads`(선: `class`, `name`, `link_id`, `lanes`), `alerts`(점: `type`, `speed_limit_kmh`, z12부터). 최대 z14, 그 이상은 클라이언트가 확대 |
| `GET /v1/basemap/{z}/{x}/{y}.png` | 브이월드 배경지도 중계(z6~19). 설정이 없으면 404 |

도로 등급별로 보이는 최소 줌이 다르다. 고속도로 z5, 국도급 z8, 간선 z10, 연결로 z11, 보조간선 z12, 이면도로 z13부터 보인다.

## 오류

`{"error": "메시지"}`와 함께 400(잘못된 요청), 404(장소 없음, 경로 없음, 도로망 밖 좌표)를 돌려준다.

## 앱이 하는 일

경로를 받은 뒤의 일은 앱(코어)이 한다. 서버는 요청이 들어올 때만 계산한다.

- **위치 맞추기**: GNSS 위치를 `geometry`에 맞춰 진행 거리를 구한다.
- **안내 정보**: 다음 안내 지점, 남은 시간·거리, ETA, HUD 값을 계산한다.
- **차로·경고 표시**: 차로 표시는 안내 지점 1 km 앞부터 보인다. 경고 범위는 단속카메라 800 m, 구간단속 1 km, 과속방지턱 200 m다.
- **이탈 판정**: max(50 m, 1.5 × GNSS 오차)보다 멀리 떨어진 위치가 3회 연속 나오면 이탈로 본다.
- **재탐색**: 이탈하면 현재 위치를 출발지로 `k=1` 요청을 보낸다. 다시 요청하기 전에 15초를 기다린다.
