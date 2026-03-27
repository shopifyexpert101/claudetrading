"""
Trade Brain - The strategic decision maker.
Uses Claude Opus for regime classification and trade decisions.
Implements crisis alpha: trades INTO fear, not away from it.
"""
import json
import anthropic
from config import settings
from utils.logger import log


class TradeBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.BRAIN_MODEL

    def decide(self, candidate: dict, sentiment: dict) -> dict:
        """Make a trade decision for a scanned candidate."""
        try:
            prompt = self._build_prompt(candidate, sentiment)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )

            return self._parse_decision(candidate["symbol"], response)

        except Exception as e:
            log.error(f"Brain decision failed for {candidate['symbol']}: {e}")
            return self._no_trade(candidate["symbol"], f"Brain error: {e}")

    def _build_prompt(self, candidate: dict, sentiment: dict) -> str:
        """Build the brain's decision prompt."""
        crisis_note = ""
        if settings.CRISIS_ALPHA_ENABLED:
            crisis_note = """
CRISIS ALPHA RULES:
- You trade INTO fear, not away from it
- Panic selling = buying opportunity for defensive stocks
- Elevated VIX/fear = INCREASE position confidence, not decrease
- These are recession-proof stocks - they BENEFIT from fear
- Only avoid if the specific company has fundamental problems"""

        return f"""You are an expert algorithmic trading strategist. Analyze this opportunity and decide.

SYMBOL: {candidate['symbol']}
CURRENT PRICE: {candidate['h1_close']}
H1 TREND: {candidate['h1_trend']}
H4 TREND: {candidate['h4_trend']}
ATR RATIO: {candidate['atr_ratio']:.3f}
ATR VALUE: {candidate['atr_value']:.5f}
VOLUME Z-SCORE: {candidate['volume_zscore']:.2f}
SPREAD: {candidate['spread']} points

SENTIMENT:
- Score: {sentiment.get('score', 0)} (-1 bearish to +1 bullish)
- Label: {sentiment.get('label', 'neutral')}
- Factors: {sentiment.get('factors', [])}
- Summary: {sentiment.get('summary', 'N/A')}

IMPORTANT: Sentiment INFORMS but NEVER blocks a trade. Even bearish sentiment on a bullish setup = trade it.
{crisis_note}

REGIME TYPES: {settings.REGIME_TYPES}

Respond in VALID JSON only:
{{
    "symbol": "{candidate['symbol']}",
    "action": "<BUY|SELL|SKIP>",
    "regime": "<trending|ranging|volatile|crisis>",
    "confidence": <float 0.0 to 1.0>,
    "entry_price": <suggested entry or current price>,
    "sl_distance_atr": <SL distance as ATR multiplier, e.g. 1.5>,
    "tp_distance_atr": <TP distance as ATR multiplier, e.g. 3.0>,
    "reasoning": "<2-3 sentence explanation>",
    "grade": "<A+|A|B|C>"
}}

Grade guidelines:
- A+: Strong trend alignment across TFs + favorable regime + high confidence
- A: Good setup with minor caveats
- B: Acceptable but not ideal
- C: Skip (return action=SKIP)"""

    def _parse_decision(self, symbol: str, response) -> dict:
        """Parse the brain's decision."""
        text = response.content[0].text.strip()

        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)

            action = data.get("action", "SKIP").upper()
            grade = data.get("grade", "C")

            # Grade C = skip
            if grade == "C" or action == "SKIP":
                return self._no_trade(symbol, data.get("reasoning", "Low grade"))

            result = {
                "symbol": symbol,
                "action": action,
                "regime": data.get("regime", "unknown"),
                "confidence": float(data.get("confidence", 0)),
                "entry_price": float(data.get("entry_price", 0)),
                "sl_distance_atr": float(data.get("sl_distance_atr", 1.5)),
                "tp_distance_atr": float(data.get("tp_distance_atr", 3.0)),
                "reasoning": data.get("reasoning", ""),
                "grade": grade,
                "trade": True,
            }

            log.info(
                f"Brain | {symbol} | {action} | Grade: {grade} | "
                f"Regime: {result['regime']} | Conf: {result['confidence']:.2f}"
            )
            return result

        except (json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to parse brain response for {symbol}: {e}")
            return self._no_trade(symbol, f"Parse error: {e}")

    def _no_trade(self, symbol: str, reason: str) -> dict:
        """Return a no-trade decision."""
        log.info(f"Brain | {symbol} | SKIP | {reason}")
        return {
            "symbol": symbol,
            "action": "SKIP",
            "trade": False,
            "reasoning": reason,
        }

    def decide_batch(self, candidates: list, sentiments: dict) -> list:
        """Process multiple candidates through the brain."""
        decisions = []
        for candidate in candidates:
            symbol = candidate["symbol"]
            sentiment = sentiments.get(symbol, {})
            decision = self.decide(candidate, sentiment)
            if decision.get("trade"):
                decisions.append(decision)

        log.info(f"Brain approved {len(decisions)}/{len(candidates)} trades")
        return decisions
