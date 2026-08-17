from travel_planner import extract_json_text


def test_extract_json_text_ignores_trailing_text_after_json():
    text = '''
    {
      "recommended_city": "순천시",
      "weather": "가을 날씨",
      "events": ["순천만갈대축제"],
      "reason": "추천 이유입니다."
    }

    추가 설명이 뒤에 붙어 있어도 첫 JSON만 파싱해야 합니다.
    '''

    data = extract_json_text(text)
    assert data["recommended_city"] == "순천시"
    assert data["events"] == ["순천만갈대축제"]


def test_extract_json_text_handles_markdown_fence():
    text = '''```json
{"recommended_city": "제주", "weather": "맑음", "events": ["축제"], "reason": "이유"}
```'''

    data = extract_json_text(text)
    assert data["recommended_city"] == "제주"
