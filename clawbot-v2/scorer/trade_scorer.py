"""
Trade Scorer using Claude Sonnet.
Scores trades 0-100 with session multipliers.
Only trades >= SCORE_MIN proceed to execution.
"""
import json
from datetime import datetime, timezone
import anthropic
from config import settings
from utils.logger import log


class TradeScorer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.SCORER_MODEL

    def score(self, decision: dict, candidate: dict, sentiment: dict) -> dict:
        """Score a trade decision 0-100."""
        try:
            prompt = self._build_prompt(decision, candidate, sentiment)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            result = self._parse_score(decision["symbol"], response)

            # Apply session multiplier
            multiplier = self._get_session_multiplier()
            result["raw_score"] = result["score"]
            result["score"] = min(100, result["score"] * multiplier)
            result["session_multiplier"] = multiplier
            result["passes"] = result["score"] >= settings.SCORE_MIN

            log.info(
                f"Scorer | {decision['symbol']} | Raw: {result['raw_score']:.0f} | "
                f"x{multiplier:.2f} = {result['score']:.0f} | "
                f"{'PASS' if result['passes'] else 'FAIL'}"
            )

            return result

        except Exception as e:
            log.error(f"Scoring failed for {decision['symbol']}: {e}")
            return {"symbol": decision["symbol"], "score": 0, "passes": False}

    def _build_prompt(self, decision: dict, candidate: dict, sentiment: dict) -> str:
        """Build the scoring prompt."""
        return f"""You are a trade quality scorer. Rate this trade setup from 0-100.

TRADE SETUP:
- Symbol: {decision['symbol']}
- Action: {decision['action']}
- Grade: {decision['grade']}
- Regime: {decision['regime']}
- Confidence: {decision['confidence']}
- Reasoning: {decision['reasoning']}

TECHNICAL DATA:
- H1 Trend: {candidate['h1_trend']}
- H4 Trend: {candidate['h4_trend']}
- ATR Ratio: {candidate['atr_ratio']:.3f}
- Volume Z-Score: {candidate['volume_zscore']:.2f}
- SL Distance (ATR): {decision['sl_distance_atr']}x
- TP Distance (ATR): {decision['tp_distance_atr']}x
- Risk:Reward: 1:{decision['tp_distance_atr'] / max(decision['sl_distance_atr'], 0.1):.1f}

SENTIMENT:
- Score: {sentiment.get('score', 0)}
- Label: {sentiment.get('label', 'neutral')}

SCORING CRITERIA:
- Trend alignment across timeframes (0-25 points)
- Risk:reward ratio quality (0-25 points)
- Volume and volatility confirmation (0-20 points)
- Setup clarity and confidence (0-15 points)
- Regime favorability (0-15 points)

Respond in VALID JSON only:
{{
    "score": <integer 0-100>,
    "breakdown": {{
        "trend_alignment": <0-25>,
        "risk_reward": <0-25>,
        "vol_confirmation": <0-20>,
        "setup_clarity": <0-15>,
        "regime_score": <0-15>
    }},
    "notes": "<brief scoring rationale>"
}}"""

    def _parse_score(self, symbol: str, response) -> dict:
        """Parse the scoring response."""
        text = response.content[0].text.strip()

        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
            return {
                "symbol": symbol,
                "score": float(data.get("score", 0)),
                "breakdown": data.get("breakdown", {}),
                "notes": data.get("notes", ""),
            }
        except (json.JSONDecodeError, ValueError):
            log.warning(f"Failed to parse score for {symbol}, defaulting to 0")
            return {"symbol": symbol, "score": 0, "breakdown": {}, "notes": "parse_error"}

    def _get_session_multiplier(self) -> float:
        """Get current trading session multiplier based on UTC hour."""
        now_utc = datetime.now(timezone.utc).hour

        best_multiplier = 1.0
        for session, info in settings.SESSION_MULTIPLIERS.items():
            start = info["start"]
            end = info["end"]
            if start <= now_utc < end:
                best_multiplier = max(best_multiplier, info["multiplier"])

        return best_multiplier

    def score_batch(self, decisions: list, candidates_map: dict, sentiments: dict) -> list:
        """Score multiple decisions, return those that pass."""
        scored = []
        for decision in decisions:
            symbol = decision["symbol"]
            candidate = candidates_map.get(symbol, {})
            sentiment = sentiments.get(symbol, {})

            result = self.score(decision, candidate, sentiment)
            decision["score_result"] = result

            if result.get("passes"):
                scored.append(decision)

        log.info(f"Scorer passed {len(scored)}/{len(decisions)} trades")
        return scored
