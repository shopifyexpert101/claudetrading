"""News sentiment analysis module with FinBERT / VADER fallback."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from utils.helpers import SYMBOL_KEYWORDS

logger = logging.getLogger("trading_bot")


@dataclass
class SentimentSignal:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    score: float  # -1.0 to 1.0
    headline: str
    source: str
    signal_type: str = "sentiment"
    description: str = ""


class SentimentAnalyzer:
    """Polls news sources, scores sentiment, and matches to symbols."""

    def __init__(self, config: dict, env: dict):
        self.config = config.get("sentiment", config)
        self.env = env
        self.bullish_threshold = self.config.get("sentiment_bullish", 0.5)
        self.bearish_threshold = self.config.get("sentiment_bearish", -0.5)
        self.use_finbert = self.config.get("use_finbert", True)
        self.finbert_timeout = self.config.get("finbert_timeout_sec", 30)

        # Article cache: hash -> (score, timestamp)
        self._cache: dict[str, tuple[float, float]] = {}
        self._cache_ttl = 3600  # 1 hour

        # Sentiment model (lazy init)
        self._model = None
        self._tokenizer = None
        self._vader = None
        self._using_vader = False

    def _init_model(self):
        """Initialize sentiment model — FinBERT or VADER fallback."""
        if not self.use_finbert:
            self._init_vader()
            return

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch

            start = time.time()
            self._tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            self._model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
            self._model.eval()
            elapsed = time.time() - start

            if elapsed > self.finbert_timeout:
                logger.warning(
                    "FinBERT loaded but took %.1fs (> %ds timeout). "
                    "Switching to VADER for faster inference.",
                    elapsed, self.finbert_timeout,
                )
                self._model = None
                self._tokenizer = None
                self._init_vader()
            else:
                logger.info("FinBERT model loaded in %.1fs", elapsed)
        except Exception as e:
            logger.warning("FinBERT unavailable (%s). Falling back to VADER.", e)
            self._init_vader()

    def _init_vader(self):
        """Initialize VADER sentiment analyzer."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
            self._using_vader = True
            logger.info("VADER sentiment analyzer initialized")
        except ImportError:
            logger.error("Neither FinBERT nor VADER available. Sentiment analysis disabled.")

    def _score_text(self, text: str) -> float:
        """Score a text string. Returns -1.0 to 1.0."""
        article_hash = hashlib.md5(text.encode()).hexdigest()

        # Check cache
        if article_hash in self._cache:
            score, ts = self._cache[article_hash]
            if time.time() - ts < self._cache_ttl:
                return score

        if self._model is not None and self._tokenizer is not None:
            score = self._score_finbert(text)
        elif self._vader is not None:
            score = self._score_vader(text)
        else:
            return 0.0

        self._cache[article_hash] = (score, time.time())
        return score

    def _score_finbert(self, text: str) -> float:
        """Score with FinBERT. Returns -1 to 1."""
        import torch

        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self._model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        # FinBERT: [positive, negative, neutral]
        positive = probs[0].item()
        negative = probs[1].item()
        return positive - negative

    def _score_vader(self, text: str) -> float:
        """Score with VADER. Returns compound score -1 to 1."""
        scores = self._vader.polarity_scores(text)
        return scores["compound"]

    def _match_symbols(self, text: str) -> list[str]:
        """Match text to trading symbols using keyword mapping."""
        text_lower = text.lower()
        matched = []
        for symbol, keywords in SYMBOL_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched.append(symbol)
                    break
        return matched

    async def fetch_news(self) -> list[dict]:
        """Fetch news from all configured sources."""
        if self._model is None and self._vader is None:
            self._init_model()

        sources = self.config.get("sources", [])
        all_articles: list[dict] = []

        tasks = []
        if "newsapi" in sources:
            tasks.append(self._fetch_newsapi())
        if "finnhub" in sources:
            tasks.append(self._fetch_finnhub())
        if "alpha_vantage" in sources:
            tasks.append(self._fetch_alpha_vantage())
        if "cryptopanic" in sources:
            tasks.append(self._fetch_cryptopanic())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("News fetch error: %s", result)
                continue
            all_articles.extend(result)

        logger.info("Fetched %d news articles from %d sources", len(all_articles), len(tasks))
        return all_articles

    async def analyze(self) -> list[SentimentSignal]:
        """Fetch news, score sentiment, return triggered signals."""
        articles = await self.fetch_news()
        signals: list[SentimentSignal] = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}"
            if not text.strip():
                continue

            matched_symbols = self._match_symbols(text)
            if not matched_symbols:
                continue

            score = await asyncio.to_thread(self._score_text, text)

            for symbol in matched_symbols:
                if score >= self.bullish_threshold:
                    signals.append(SentimentSignal(
                        symbol=symbol, direction="LONG", score=score,
                        headline=article.get("title", "")[:200],
                        source=article.get("source", "unknown"),
                        description=f"Bullish sentiment (score: {score:.2f}): {article.get('title', '')[:100]}",
                    ))
                elif score <= self.bearish_threshold:
                    signals.append(SentimentSignal(
                        symbol=symbol, direction="SHORT", score=score,
                        headline=article.get("title", "")[:200],
                        source=article.get("source", "unknown"),
                        description=f"Bearish sentiment (score: {score:.2f}): {article.get('title', '')[:100]}",
                    ))

        return signals

    def get_sentiment_for_symbol(self, symbol: str) -> Optional[float]:
        """Get latest cached sentiment score for a symbol. Returns None if unavailable."""
        # Search cache for articles mentioning this symbol
        scores = []
        for article_hash, (score, ts) in self._cache.items():
            if time.time() - ts < self._cache_ttl:
                scores.append(score)
        # This is approximate — in production you'd index by symbol
        return sum(scores) / len(scores) if scores else None

    # ------------------------------------------------------------------
    # News source fetchers
    # ------------------------------------------------------------------

    async def _fetch_newsapi(self) -> list[dict]:
        """Fetch from NewsAPI."""
        api_key = self.env.get("NEWSAPI_KEY", "")
        if not api_key:
            return []

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": "trading OR stock OR crypto OR forex OR commodity",
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 50,
                    "apiKey": api_key,
                }
                async with session.get(
                    "https://newsapi.org/v2/everything",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("NewsAPI returned %d", resp.status)
                        return []
                    data = await resp.json()
                    articles = data.get("articles", [])
                    return [
                        {
                            "title": a.get("title", ""),
                            "description": a.get("description", ""),
                            "source": "newsapi",
                        }
                        for a in articles
                    ]
        except Exception as e:
            logger.error("NewsAPI error: %s", e)
            return []

    async def _fetch_finnhub(self) -> list[dict]:
        """Fetch from Finnhub."""
        api_key = self.env.get("FINNHUB_API_KEY", "")
        if not api_key:
            return []

        try:
            async with aiohttp.ClientSession() as session:
                params = {"category": "general", "token": api_key}
                async with session.get(
                    "https://finnhub.io/api/v1/news",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Finnhub returned %d", resp.status)
                        return []
                    data = await resp.json()
                    return [
                        {
                            "title": a.get("headline", ""),
                            "description": a.get("summary", ""),
                            "source": "finnhub",
                        }
                        for a in data
                    ]
        except Exception as e:
            logger.error("Finnhub error: %s", e)
            return []

    async def _fetch_alpha_vantage(self) -> list[dict]:
        """Fetch from Alpha Vantage news sentiment."""
        api_key = self.env.get("ALPHA_VANTAGE_KEY", "")
        if not api_key:
            return []

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "function": "NEWS_SENTIMENT",
                    "topics": "financial_markets,forex,economy_macro",
                    "limit": 50,
                    "apikey": api_key,
                }
                async with session.get(
                    "https://www.alphavantage.co/query",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Alpha Vantage returned %d", resp.status)
                        return []
                    data = await resp.json()
                    feed = data.get("feed", [])
                    return [
                        {
                            "title": a.get("title", ""),
                            "description": a.get("summary", ""),
                            "source": "alpha_vantage",
                        }
                        for a in feed
                    ]
        except Exception as e:
            logger.error("Alpha Vantage error: %s", e)
            return []

    async def _fetch_cryptopanic(self) -> list[dict]:
        """Fetch from CryptoPanic."""
        api_key = self.env.get("CRYPTOPANIC_API_KEY", "")
        if not api_key:
            return []

        try:
            async with aiohttp.ClientSession() as session:
                params = {"auth_token": api_key, "public": "true"}
                async with session.get(
                    "https://cryptopanic.com/api/v1/posts/",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("CryptoPanic returned %d", resp.status)
                        return []
                    data = await resp.json()
                    results = data.get("results", [])
                    return [
                        {
                            "title": a.get("title", ""),
                            "description": a.get("title", ""),  # CryptoPanic has title only
                            "source": "cryptopanic",
                        }
                        for a in results
                    ]
        except Exception as e:
            logger.error("CryptoPanic error: %s", e)
            return []
