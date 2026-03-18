"""Alert message formatting for Telegram (Markdown) and WhatsApp (plain text)."""

from __future__ import annotations

from datetime import datetime, timezone

from alerts.confidence import ConfidenceScore
from alerts.sl_tp import SLTPLevels
from utils.helpers import format_price, pct_change, progress_bar


def format_telegram(
    symbol: str,
    direction: str,
    exchange: str,
    asset_class: str,
    trigger: str,
    sentiment_label: str,
    sentiment_score: float,
    levels: SLTPLevels,
    confidence: ConfidenceScore,
) -> str:
    """Build Telegram Markdown alert message."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    ac_display = asset_class.capitalize()
    fp = lambda p: format_price(p, asset_class, symbol)

    sl_pct = pct_change(levels.entry, levels.stop_loss)
    tp1_pct = pct_change(levels.entry, levels.tp1)
    tp2_pct = pct_change(levels.entry, levels.tp2)
    tp3_pct = pct_change(levels.entry, levels.tp3)

    sig_bar = progress_bar(confidence.signal_strength)
    vol_bar = progress_bar(confidence.volume_confirmation)
    trend_bar = progress_bar(confidence.trend_alignment)
    sent_bar = progress_bar(confidence.sentiment_alignment)

    msg = (
        f"\U0001f6a8 *TRADE ALERT — {symbol} {direction}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\U0001f4cd *Exchange:*   {exchange}\n"
        f"\U0001f4c2 *Class:*      {ac_display}\n"
        f"\U0001f4cc *Trigger:*    {trigger}\n"
        f"\U0001f4f0 *Sentiment:*  {sentiment_label} — score: {sentiment_score:.2f}\n"
        f"\u23f0 *Time:*       {now}\n"
        f"\n"
        f"\U0001f4b0 *Entry:*      {fp(levels.entry)}\n"
        f"\U0001f6d1 *Stop Loss:*  {fp(levels.stop_loss)}  ({sl_pct})\n"
        f"\U0001f3af *TP1:*        {fp(levels.tp1)}  ({tp1_pct})\n"
        f"\U0001f3af *TP2:*        {fp(levels.tp2)}  ({tp2_pct})\n"
        f"\U0001f3af *TP3:*        {fp(levels.tp3)}  ({tp3_pct})\n"
        f"\u2696\ufe0f *R:R Ratio:*  1:{levels.risk_reward:.1f}\n"
        f"\n"
        f"\U0001f9e0 *CONFIDENCE: {confidence.total:.0f}%*\n"
        f"    Signal:    {confidence.signal_strength:.0f}%  {sig_bar}\n"
        f"    Volume:    {confidence.volume_confirmation:.0f}%  {vol_bar}\n"
        f"    Trend:     {confidence.trend_alignment:.0f}%  {trend_bar}\n"
        f"    Sentiment: {confidence.sentiment_alignment:.0f}%  {sent_bar}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\u26a0\ufe0f _For informational purposes only. Not financial advice._"
    )
    return msg


def format_whatsapp(
    symbol: str,
    direction: str,
    exchange: str,
    asset_class: str,
    trigger: str,
    sentiment_label: str,
    sentiment_score: float,
    levels: SLTPLevels,
    confidence: ConfidenceScore,
) -> str:
    """Build WhatsApp plain-text alert message."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    ac_display = asset_class.capitalize()
    fp = lambda p: format_price(p, asset_class, symbol)

    sl_pct = pct_change(levels.entry, levels.stop_loss)
    tp1_pct = pct_change(levels.entry, levels.tp1)
    tp2_pct = pct_change(levels.entry, levels.tp2)
    tp3_pct = pct_change(levels.entry, levels.tp3)

    sig_bar = progress_bar(confidence.signal_strength)
    vol_bar = progress_bar(confidence.volume_confirmation)
    trend_bar = progress_bar(confidence.trend_alignment)
    sent_bar = progress_bar(confidence.sentiment_alignment)

    msg = (
        f"TRADE ALERT -- {symbol} {direction}\n"
        f"-------------------------------\n"
        f"Exchange:   {exchange}\n"
        f"Class:      {ac_display}\n"
        f"Trigger:    {trigger}\n"
        f"Sentiment:  {sentiment_label} -- score: {sentiment_score:.2f}\n"
        f"Time:       {now}\n"
        f"\n"
        f"Entry:      {fp(levels.entry)}\n"
        f"Stop Loss:  {fp(levels.stop_loss)}  ({sl_pct})\n"
        f"TP1:        {fp(levels.tp1)}  ({tp1_pct})\n"
        f"TP2:        {fp(levels.tp2)}  ({tp2_pct})\n"
        f"TP3:        {fp(levels.tp3)}  ({tp3_pct})\n"
        f"R:R Ratio:  1:{levels.risk_reward:.1f}\n"
        f"\n"
        f"CONFIDENCE: {confidence.total:.0f}%\n"
        f"    Signal:    {confidence.signal_strength:.0f}%  {sig_bar}\n"
        f"    Volume:    {confidence.volume_confirmation:.0f}%  {vol_bar}\n"
        f"    Trend:     {confidence.trend_alignment:.0f}%  {trend_bar}\n"
        f"    Sentiment: {confidence.sentiment_alignment:.0f}%  {sent_bar}\n"
        f"-------------------------------\n"
        f"For informational purposes only. Not financial advice."
    )
    return msg
