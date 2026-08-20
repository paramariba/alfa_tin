import asyncio
import json

import httpx

from app.news import NewsArticle, PortfolioNewsService, parse_google_news_rss


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item><title>Sber reports record profit - Reuters</title><link>https://example.com/1</link><pubDate>Wed, 19 Aug 2026 10:00:00 GMT</pubDate><description><![CDATA[<b>Profit increased</b>]]></description><source>Reuters</source></item>
  <item><title>Sber reports record profit - Reuters</title><link>https://example.com/duplicate</link><source>Reuters</source></item>
  <item><title>New dividend policy</title><link>https://example.com/2</link><source>Interfax</source></item>
</channel></rss>"""


def test_rss_parser_strips_html_and_deduplicates():
    articles = parse_google_news_rss(RSS, limit=5)
    assert len(articles) == 2
    assert articles[0].summary == "Profit increased"
    assert articles[0].source == "Reuters"


def test_gemini_analysis_uses_structured_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    request_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload.update(json.loads(request.content))
        result = {
            "headline": "Сбер сообщил о рекордной прибыли",
            "event_summary": "Банк опубликовал новый финансовый результат.",
            "conclusion": "Рост прибыли укрепляет финансовую устойчивость бизнеса.",
            "facts": ["Прибыль выросла"],
            "source_agreement": "single_source",
        }
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(result, ensure_ascii=False)}]}}]})

    article = NewsArticle("Сбер увеличил прибыль", "https://example.com", "Источник", "2026-08-19T10:00:00Z", "")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PortfolioNewsService(client=client)
            result = await service.analyze("SBER", "Сбербанк", 277.0, -0.2, [article])
            assert result["source_agreement"] == "single_source"
            assert result["method"] == "gemini"

    asyncio.run(scenario())
    assert request_payload["generationConfig"]["responseMimeType"] == "application/json"
    assert request_payload["generationConfig"]["responseSchema"]["required"]
    prompt = request_payload["contents"][0]["parts"][0]["text"]
    assert "для подростка 14–17 лет" in prompt
    assert "фактический заголовок из 4–10 слов" in prompt
    assert "Не предсказывай цену акции" in prompt


def test_analysis_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    article = NewsArticle("Компания сообщила о росте прибыли", "https://example.com", "Источник", "2026-08-19T10:00:00Z", "")
    service = PortfolioNewsService(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))))
    result = asyncio.run(service.analyze("SBER", "Сбербанк", 277.0, 0.0, [article]))
    asyncio.run(service.close())
    assert result["method"] == "heuristic"
    assert result["headline"] == "Компания сообщила о росте прибыли"
    assert result["source_agreement"] == "single_source"
    assert result["copy_version"] == PortfolioNewsService.COPY_VERSION
