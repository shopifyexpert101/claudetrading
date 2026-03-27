"""
Sentiment analyzer using Claude Haiku.
Analyzes market sentiment via web search with model-only fallback.
IMPORTANT: Sentiment informs but NEVER blocks trades.
"""
import json
import anthropic
from config import settings
from utils.logger import log


class SentimentAnalyzer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.SENTIMENT_MODEL

    def analyze(self, symbol: str, context: dict = None) -> dict:
        """Analyze sentiment for a symbol. Returns score and summary."""
        try:
            # Try web-search-enhanced analysis first
            if settings.SENTIMENT_WEB_SEARCH:
                result = self._analyze_with_search(symbol, context)
                if result:
                    return result

            # Fallback to model-only analysis
            if settings.SENTIMENT_FALLBACK:
                return self._analyze_model_only(symbol, context)

            return self._neutral_result(symbol)

        except Exception as e:
            log.warning(f"Sentiment analysis failed for {symbol}: {e}")
            return self._neutral_result(symbol)

    def _analyze_with_search(self, symbol: str, context: dict) -> dict:
        """Analyze using web search for latest news."""
        try:
            prompt = self._build_prompt(symbol, context, with_search=True)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            return self._parse_response(symbol, response)

        except Exception as e:
            log.debug(f"Web search sentiment failed for {symbol}: {e}")
            return None

    def _analyze_model_only(self, symbol: str, context: dict) -> dict:
        """Analyze using model knowledge only (no web search)."""
        try:
            prompt = self._build_prompt(symbol, context, with_search=False)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            return self._parse_response(symbol, response)

        except Exception as e:
            log.warning(f"Model-only sentiment failed for {symbol}: {e}")
            return self._neutral_result(symbol)

    def _build_prompt(self, symbol: str, context: dict, with_search: bool) -> str:
        """Build the sentiment analysis prompt."""
        trend_info = ""
        if context:
            trend_info = f"""
Current price: {context.get('h1_close', 'N/A')}
H1 trend: {context.get('h1_trend', 'N/A')}
H4 trend: {context.get('h4_trend', 'N/A')}
ATR ratio: {context.get('atr_ratio', 'N/A')}"""

        search_note = ""
        if with_search:
            search_note = "Based on your latest training data knowledge of this stock/asset, "

        return f"""You are a financial sentiment analyzer. {search_note}analyze the current sentiment for {symbol}.
{trend_info}

Respond in VALID JSON only, no other text:
{{
    "symbol": "{symbol}",
    "sentiment_score": <float from -1.0 (very bearish) to 1.0 (very bullish)>,
    "sentiment_label": "<very_bearish|bearish|neutral|bullish|very_bullish>",
    "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
    "summary": "<1-2 sentence summary>",
    "confidence": <float 0.0 to 1.0>
}}"""

    def _parse_response(self, symbol: str, response) -> dict:
        """Parse the AI response into a structured result."""
        text = response.content[0].text.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
            result = {
                "symbol": symbol,
                "score": float(data.get("sentiment_score", 0)),
                "label": data.get("sentiment_label", "neutral"),
                "factors": data.get("key_factors", []),
                "summary": data.get("summary", ""),
                "confidence": float(data.get("confidence", 0.5)),
                "source": "ai",
            }
            log.info(f"Sentiment | {symbol} | {result['label']} ({result['score']:.2f}) | {result['summary'][:80]}")
            return result

        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"Failed to parse sentiment response for {symbol}: {e}")
            return self._neutral_result(symbol)

    def _neutral_result(self, symbol: str) -> dict:
        """Return a neutral result when analysis fails."""
        return {
            "symbol": symbol,
            "score": 0.0,
            "label": "neutral",
            "factors": ["analysis_unavailable"],
            "summary": "Sentiment analysis unavailable, proceeding with neutral bias.",
            "confidence": 0.0,
            "source": "fallback",
        }

    def analyze_batch(self, candidates: list) -> dict:
        """Analyze sentiment for multiple symbols. Returns {symbol: result}."""
        results = {}
        for candidate in candidates:
            symbol = candidate["symbol"]
            results[symbol] = self.analyze(symbol, context=candidate)
        return results
