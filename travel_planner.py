#!/usr/bin/env python3
"""
CLI 기반 국내 여행 추천 시스템
- LLM: GEMINI Chat Completions API
- 장소 검색: Kakao Local Keyword Search API
- 입력: --date / -date "YYYY-MM-DD"
"""

import argparse
import json
import os
import sys

from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT = 30


def log(message: str) -> None:
    print(message, flush=True)


def add_error(errors: list[dict[str, str]], step: str, error_type: str, message: str) -> None:
    errors.append({
        "step": step,
        "type": error_type,
        "message": message[:500],
    })


def validate_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: {value!r}. YYYY-MM-DD 형식을 사용하세요."
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="날짜를 입력하면 LLM 여행 추천 → Kakao 맛집 검색 → Markdown 리포트를 생성합니다."
    )
    parser.add_argument(
        "-date", "--date",
        required=True,
        type=validate_date,
        help="여행 날짜 (YYYY-MM-DD)",
    )
    return parser.parse_args()


def require_api_keys() -> tuple[str, str]:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    kakao_key = os.getenv("KAKAO_REST_API_KEY", "").strip()

    missing = []
    if not gemini_key:
        missing.append("GEMINI_API_KEY")
    if not kakao_key:
        missing.append("KAKAO_REST_API_KEY")

    if missing:
        log("오류: API 키가 설정되지 않았습니다.")
        log("필수 키: " + ", ".join(missing))
        log("macOS/Linux: export GEMINI_API_KEY=\"YOUR_KEY\"")
        log("macOS/Linux: export KAKAO_REST_API_KEY=\"YOUR_KEY\"")
        log("Windows PowerShell: $env:GEMINI_API_KEY=\"YOUR_KEY\"")
        log("Windows PowerShell: $env:KAKAO_REST_API_KEY=\"YOUR_KEY\"")
        log("또는 .env 파일에 키를 설정한 뒤 다시 실행하세요.")
        sys.exit(1)

    return gemini_key, kakao_key


def extract_json_text(text: str) -> dict[str, Any]:
    """LLM이 JSON 외의 설명/코드블록을 붙였을 때 첫 유효 JSON 객체만 추출한다."""
    if not isinstance(text, str):
        raise TypeError("JSON 추출 대상은 문자열이어야 합니다.")

    normalized = text.strip()
    if not normalized:
        raise ValueError("빈 JSON 응답입니다.")

    # ```json ... ``` 또는 ``` ... ``` 형태까지 정리
    if normalized.startswith("```"):
        normalized = normalized.strip("`")
        if "\n" in normalized:
            lines = normalized.splitlines()
            if lines and lines[0].strip().lower() in {"json", "javascript"}:
                normalized = "\n".join(lines[1:])
        normalized = normalized.strip()

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        start = normalized.find("{")
        if start == -1:
            raise

        decoder = json.JSONDecoder()
        for idx in range(start, len(normalized)):
            candidate = normalized[idx:]
            try:
                value, end_index = decoder.raw_decode(candidate)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue

        # 마지막 수단: 첫 '{'부터 마지막 '}' 사이만 잘라서 파싱 시도
        end = normalized.rfind("}")
        if end > start:
            return json.loads(normalized[start:end + 1])

        raise


def validate_recommendation(data: dict[str, Any]) -> dict[str, Any]:
    required = {
        "recommended_city": str,
        "weather": str,
        "events": list,
        "reason": str,
    }
    for key, expected_type in required.items():
        if key not in data:
            raise ValueError(f"필수 키 누락: {key}")
        if not isinstance(data[key], expected_type):
            raise ValueError(f"필수 키 타입 오류: {key}")

    if not isinstance(data["events"], list) or not all(isinstance(x, str) for x in data["events"]):
        raise ValueError("events는 문자열 배열이어야 합니다.")

    # 과도하게 긴/많은 이벤트를 결과 스키마에 맞게 제한
    data["events"] = data["events"][:3]
    return data


def gemini_chat(api_key: str, messages: list[dict[str, str]], json_mode: bool = False) -> str:
    """Google Gemini API를 권장되는 Chat API 경로로 호출합니다."""
    client = genai.Client(api_key=api_key)

    prompt_parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            prompt_parts.append(f"[SYSTEM]\n{content}")
        else:
            prompt_parts.append(f"[USER]\n{content}")

    prompt = "\n\n".join(prompt_parts)

    config = None
    if json_mode:
        config = types.GenerateContentConfig(response_mime_type="application/json")

    preferred_models = []
    configured = os.getenv("GEMINI_MODEL", "").strip()
    if configured:
        preferred_models.append(configured)
    preferred_models.extend([
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
    ])

    # 모델이 새 계정에서 비활성화된 경우를 대비해 순차적으로 폴백합니다.
    seen = set()
    last_exc: Exception | None = None
    for model_name in preferred_models:
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)

        try:
            chat = client.chats.create(
                model=model_name,
                config=config,
            )
            response = chat.send_message(prompt)
            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError("Gemini API 응답이 비어 있습니다.")
            return text
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "401" in msg or "403" in msg or "UNAUTHENTICATED" in msg:
                raise RuntimeError("AUTH_ERROR: Gemini API 키 또는 권한을 확인하세요.") from exc
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise RuntimeError("QUOTA_OR_RATE_LIMIT: Gemini API 사용량 한도를 확인하세요.") from exc
            # 404/NOT_FOUND이면 다른 모델 후보를 하나 더 시도합니다.
            if "404" not in msg and "NOT_FOUND" not in msg:
                raise RuntimeError(f"GEMINI_API_ERROR: {msg[:500]}") from exc

    if last_exc is not None:
        raise RuntimeError(f"GEMINI_API_ERROR: {str(last_exc)[:500]}") from last_exc
    raise RuntimeError("GEMINI_API_ERROR: 사용 가능한 Gemini 모델을 찾지 못했습니다.")

def make_first_prompt(date: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "당신은 국내 여행 추천 도우미입니다. "
                "사용자가 지정한 날짜에 맞춰 국내 여행지 한 곳을 추천하세요. "
                "실제 현재 날씨나 행사 확정 정보가 아니라 해당 시기의 일반적인 특징과 행사 후보를 "
                "추천하는 교육용 과제입니다."
            ),
        },
        {
            "role": "user",
            "content": f"""
여행 날짜: {date}

반드시 JSON 객체 하나만 출력하세요. Markdown 코드블록이나 설명을 붙이지 마세요.
필수 스키마:
{{
  "recommended_city": "string",
  "weather": "string",
  "events": ["string", "string", "string"],
  "reason": "string"
}}

규칙:
- recommended_city는 한국의 도시/지역명 1개.
- events는 1~3개의 행사/축제 후보 문자열 배열.
- reason은 추천 근거 2~4문장.
- weather는 해당 시기의 일반적인 날씨 요약.
""".strip(),
        },
    ]


def get_first_recommendation(api_key: str, date: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    messages = make_first_prompt(date)
    try:
        raw = gemini_chat(api_key, messages, json_mode=True)
        return validate_recommendation(extract_json_text(raw))
    except Exception as first_exc:
        add_error(errors, "llm_recommendation", "JSON_PARSE_OR_API_ERROR", str(first_exc))
        log(f"  - 1차 JSON 처리 실패: {first_exc}")
        log("  - 필수 키만 다시 JSON으로 출력하도록 1회 재시도합니다.")

        retry_messages = messages + [{
            "role": "user",
            "content": (
                "재시도입니다. 이전 응답을 무시하고 다음 4개 키만 가진 유효한 JSON 객체를 "
                "한 줄로 다시 출력하세요: recommended_city, weather, events, reason. "
                "추가 문장과 Markdown은 절대 출력하지 마세요."
            ),
        }]
        try:
            raw = gemini_chat(api_key, retry_messages, json_mode=True)
            return validate_recommendation(extract_json_text(raw))
        except Exception as second_exc:
            add_error(errors, "llm_recommendation", "RETRY_FAILED", str(second_exc))
            raise RuntimeError("LLM 1차 추천 생성에 실패했습니다. 재시도도 실패했습니다.") from second_exc


def search_restaurants(kakao_key: str, city: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    query = f"{city} 맛집"
    try:
        response = requests.get(
            KAKAO_URL,
            headers={"Authorization": f"KakaoAK {kakao_key}"},
            params={"query": query, "size": 5, "page": 1},
            timeout=TIMEOUT,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(f"AUTH_ERROR HTTP {response.status_code}")
        if response.status_code == 429:
            raise RuntimeError("QUOTA_OR_RATE_LIMIT HTTP 429")
        response.raise_for_status()

        body = response.json()
        documents = body.get("documents", [])
        restaurants = []

        for item in documents[:5]:
            try:
                restaurants.append({
                    "name": str(item.get("place_name", "")),
                    "address": str(
                        item.get("road_address_name")
                        or item.get("address_name")
                        or ""
                    ),
                    "category": str(item.get("category_name", "")),
                    "url": str(item.get("place_url", "")),
                    "x": float(item["x"]) if item.get("x") not in (None, "") else None,
                    "y": float(item["y"]) if item.get("y") not in (None, "") else None,
                })
            except (TypeError, ValueError) as exc:
                add_error(errors, "place_search", "PARSING_ERROR", str(exc))

        if not restaurants:
            add_error(
                errors,
                "place_search",
                "EMPTY_RESULT",
                f"0 results for query={query}",
            )
        return restaurants

    except Exception as exc:
        add_error(errors, "place_search", "API_ERROR", str(exc))
        return []


def make_report_prompt(
    date: str,
    recommendation: dict[str, Any],
    restaurants: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "당신은 국내 여행 리포트를 작성하는 편집자입니다. "
                "제공된 JSON만 근거로 간결하고 실용적인 Markdown 리포트를 작성하세요. "
                "맛집 데이터가 0건이면 임의의 식당을 만들지 말고 '데이터 없음'으로 표시하세요."
            ),
        },
        {
            "role": "user",
            "content": f"""
여행 날짜: {date}

[1차 추천 JSON]
{json.dumps(recommendation, ensure_ascii=False, indent=2)}

[맛집 검색 결과]
{json.dumps(restaurants, ensure_ascii=False, indent=2)}

[오류 목록]
{json.dumps(errors, ensure_ascii=False, indent=2)}

다음 구조의 Markdown으로 작성하세요.

# {date} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 1일 일정 제안
### 오전
### 오후
### 저녁
## 오류 요약(errors)

주의:
- 확인되지 않은 세부 사실이나 식당 정보를 새로 만들지 마세요.
- 맛집은 입력 데이터에 있는 항목만 사용하세요.
- 오류가 없으면 '없음'으로 표시하세요.
""".strip(),
        },
    ]


def generate_report(
    api_key: str,
    date: str,
    recommendation: dict[str, Any],
    restaurants: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> str:
    raw = gemini_chat(
        api_key,
        make_report_prompt(date, recommendation, restaurants, errors),
        json_mode=False,
    )
    return raw.strip()


def save_results(
    date: str,
    recommendation: dict[str, Any],
    restaurants: list[dict[str, Any]],
    errors: list[dict[str, str]],
    report: str,
) -> tuple[Path, Path]:
    results_dir = Path("results")
    results_dir.mkdir(parents=True, exist_ok=True)

    json_path = results_dir / f"{date}_travel_data.json"
    md_path = results_dir / f"{date}_travel_plan.md"

    payload = {
        "date": date,
        "first_recommendation": recommendation,
        "restaurant_search_results": restaurants,
        "errors": errors,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(report + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    load_dotenv()
    args = parse_args()
    gemini_key, kakao_key = require_api_keys()

    errors: list[dict[str, str]] = []

    log(f"여행 추천 프로그램 시작: {args.date}")

    log("\n[1/3] 1차 추천 생성 중(LLM)...")
    recommendation = get_first_recommendation(gemini_key, args.date, errors)
    log(f'  - recommended_city: "{recommendation["recommended_city"]}"')

    log("\n[2/3] 맛집 검색 중(지도/장소 API)...")
    restaurants = search_restaurants(
        kakao_key,
        recommendation["recommended_city"],
        errors,
    )
    if restaurants:
        log(f"  - 맛집 {len(restaurants)}곳 검색 완료")
    else:
        log("  - 검색 결과 0건 또는 API 실패")
        log("  - 맛집 섹션을 '데이터 없음'으로 처리하고 다음 단계로 진행합니다.")

    log("\n[3/3] 최종 리포트 생성 중(LLM)...")
    try:
        report = generate_report(
            gemini_key,
            args.date,
            recommendation,
            restaurants,
            errors,
        )
        log("  - 리포트 생성 완료")
    except Exception as exc:
        add_error(errors, "final_report", "LLM_API_ERROR", str(exc))
        # 최종 리포트 API까지 실패하더라도 원본 데이터는 남긴다.
        report = f"""# {args.date} 국내 여행 추천 리포트

## 추천 지역
{recommendation["recommended_city"]}

## 추천 이유
{recommendation["reason"]}

## 날씨 요약
{recommendation["weather"]}

## 행사/축제
{chr(10).join(f"- {e}" for e in recommendation["events"])}

## 맛집 추천
- {"데이터 없음" if not restaurants else "최종 리포트 생성 API 실패로 원본 JSON을 확인하세요."}

## 1일 일정 제안
### 오전
추천 지역 이동 및 주요 관광지 탐방

### 오후
지역 문화·관광 콘텐츠 체험

### 저녁
지역 음식점 이용 및 귀가/숙박

## 오류 요약(errors)
{json.dumps(errors, ensure_ascii=False, indent=2)}
"""
        log("  - 최종 리포트 API 오류가 발생하여 기본 리포트를 저장합니다.")

    # 최종 API 호출 과정에서 추가된 errors까지 JSON에 반영
    json_path, md_path = save_results(
        args.date, recommendation, restaurants, errors, report
    )

    log("\n완료!")
    log(f"  - 원본 데이터: {json_path}")
    log(f"  - 최종 리포트: {md_path}")


if __name__ == "__main__":
    main()
