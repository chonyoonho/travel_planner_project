# 국내 여행 추천 시스템

날짜를 입력하면 다음 3단계를 순서대로 수행하는 CLI 기반 Python 프로그램입니다.

1. OpenAI API → 여행 지역·날씨·행사 후보를 구조화된 JSON으로 생성
2. Kakao Local API → 추천 지역의 맛집 5곳 검색
3. OpenAI API → 1차 추천 JSON + 맛집 검색 결과를 Markdown 여행 리포트로 생성

## 1. 개발 환경

- Python 3.10 이상
- 터미널 실행
- 인터넷 연결
- OpenAI API Key
- Kakao Developers REST API Key

## 2. 설치

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. API 키 설정

`.env.example`을 `.env`로 복사한 뒤 실제 키를 입력하거나 환경변수로 설정합니다.

### `.env` 방식

```text
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
KAKAO_REST_API_KEY=YOUR_KAKAO_REST_API_KEY
```

### macOS/Linux

```bash
export OPENAI_API_KEY="YOUR_KEY"
export KAKAO_REST_API_KEY="YOUR_KEY"
```

### Windows PowerShell

```powershell
$env:OPENAI_API_KEY="YOUR_KEY"
$env:KAKAO_REST_API_KEY="YOUR_KEY"
```

실제 키 값은 README, 소스 코드, 로그, JSON, Markdown, Git 저장소에 절대 작성하지 않습니다.

## 4. 실행

```bash
python travel_planner.py --date "2026-08-17"
```

또는 과제에서 요구한 형태:

```bash
python travel_planner.py -date "2026-08-17"
```

날짜 형식이 잘못되면 argparse 사용법과 오류 메시지를 출력하고 종료합니다.

예:

```text
python travel_planner.py --date "2026/08/17"
```

## 5. 실행 흐름

```text
입력 날짜
   ↓
[1] OpenAI API
   ↓
구조화 JSON
recommended_city / weather / events / reason
   ↓
[2] Kakao Local API
   ↓
맛집 5곳
name / address / category / url / x / y
   ↓
[3] OpenAI API
   ↓
Markdown 여행 리포트
   ↓
results/
```

## 6. 결과물

정상 실행하면 `results/` 폴더에 다음 2개 파일이 생성됩니다.

```text
results/
├── 2026-08-17_travel_data.json
└── 2026-08-17_travel_plan.md
```

### 원본 JSON

원본 JSON에는 최소한 다음이 들어갑니다.

```json
{
  "date": "2026-08-17",
  "first_recommendation": {
    "recommended_city": "제주",
    "weather": "...",
    "events": ["...", "..."],
    "reason": "..."
  },
  "restaurant_search_results": [],
  "errors": []
}
```

맛집 검색이 실패하거나 0건이면 `restaurant_search_results`는 빈 배열로 저장하고 최종 리포트 생성은 계속합니다.

## 7. 오류 처리

### API 키 미설정

프로그램을 즉시 종료하고 필요한 환경변수 이름과 설정 방법을 안내합니다.

### Kakao API 실패

401/403 인증 오류, 429 쿼터/요청 제한, 네트워크 오류 등을 `errors`에 기록하고 맛집을 `데이터 없음`으로 처리한 뒤 최종 리포트를 계속 생성합니다.

### LLM JSON 파싱 실패

1차 추천 JSON 파싱이 실패하면 필수 키만 출력하도록 프롬프트를 수정하여 최대 1회 재시도합니다. 무한 재시도는 하지 않습니다.

### 최종 리포트 API 실패

원본 JSON은 저장하고 기본 Markdown 리포트를 생성하여 결과를 남깁니다.

## 8. 보안 주의사항

API 키를 코드에 직접 작성하면 다음 문제가 발생할 수 있습니다.

- GitHub 등 공유 저장소에 키가 유출될 수 있음
- 다른 사람이 키를 사용해 과금/쿼터를 소모할 수 있음
- 키를 교체할 때 소스 코드를 수정해야 함
- 협업·배포 환경에서 비밀정보 관리가 어려워짐

따라서 이 프로젝트는 `os.getenv()`와 `.env`를 사용합니다.

`.env`는 `.gitignore`에 포함되어 있으므로 Git에 올리지 않는 것을 전제로 합니다.

## 9. REST API 학습 포인트

### GET

Kakao Local 장소 검색은 HTTP GET 요청으로 검색어를 전달합니다.

```text
GET /v2/local/search/keyword.json?query=제주 맛집
```

인증 정보는 요청 헤더에 전달합니다.

```text
Authorization: KakaoAK <REST_API_KEY>
```

### POST

OpenAI 호출은 요청 본문에 모델과 메시지 등의 JSON 데이터를 전달하기 위해 POST를 사용합니다.

즉, GET은 조회 중심, POST는 요청 본문에 데이터를 담아 서버에 처리를 요청하는 용도로 자주 사용됩니다.

## 10. API 제공자

### OpenAI

LLM이 여행지·날씨·행사 후보를 JSON으로 구조화하고, 최종 Markdown 리포트를 생성합니다.

### Kakao Local

추천된 `recommended_city`를 입력값으로 사용하여 `"{도시} 맛집"` 키워드 검색을 수행합니다.

Kakao Local 응답에서 `place_name`, `category_name`, `address_name`, `road_address_name`, `x`, `y`, `place_url` 등을 필요한 필드로 변환합니다.

## 11. 실행 로그 예시

```text
여행 추천 프로그램 시작: 2026-08-17

[1/3] 1차 추천 생성 중(LLM)...
  - recommended_city: "제주"

[2/3] 맛집 검색 중(지도/장소 API)...
  - 맛집 5곳 검색 완료

[3/3] 최종 리포트 생성 중(LLM)...
  - 리포트 생성 완료

완료!
  - 원본 데이터: results/2026-08-17_travel_data.json
  - 최종 리포트: results/2026-08-17_travel_plan.md
```

## 12. 참고 문서

- OpenAI API 공식 문서: https://platform.openai.com/docs/
- Kakao Developers Local API 공식 문서: https://developers.kakao.com/docs/latest/ko/local/dev-guide

> API의 모델명·요금·쿼터·세부 정책은 변경될 수 있으므로 실제 실행 시 해당 제공자의 공식 문서를 확인하세요.
