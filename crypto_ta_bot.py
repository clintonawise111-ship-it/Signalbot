import asyncio
import logging
import os
from datetime import datetime

import ccxt
import pandas as pd
import requests
import ta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("8862009111:AAFtbGMbE2WhYlv4BC0O1-n0A6rlaSdfPPM")
CRYPTO_PANIC_KEY = os.getenv("CRYPTO_PANIC_KEY")  # Free at cryptopanic.com

exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

# Your 40 non-stablecoin list -> Binance USDT format
# NOTE: fixed "PE/USDT" -> "PEPE/USDT" (was likely a typo; update if you meant something else)
TOP_40 = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT", "DOGE/USDT", "TRX/USDT", "ADA/USDT",
    "HYPE/USDT", "SUI/USDT", "LINK/USDT", "AVAX/USDT", "XLM/USDT", "SHIB/USDT", "HBAR/USDT", "BCH/USDT",
    "TON/USDT", "LTC/USDT", "DOT/USDT", "UNI/USDT", "PEPE/USDT", "XMR/USDT", "AAVE/USDT", "NEAR/USDT",
    "ETC/USDT", "ICP/USDT", "APT/USDT", "TAO/USDT", "MNT/USDT", "VET/USDT", "ARB/USDT", "ATOM/USDT",
    "RENDER/USDT", "FIL/USDT", "KAS/USDT", "ALGO/USDT", "TIA/USDT", "TRUMP/USDT", "CRO/USDT", "OP/USDT",
]

# Markets are loaded once at startup instead of on every single TA call
_markets_loaded = False


def ensure_markets_loaded():
    global _markets_loaded
    if not _markets_loaded:
        exchange.load_markets()
        _markets_loaded = True


def get_ta_signal(symbol, timeframe="1h"):
    try:
        ensure_markets_loaded()
        if symbol not in exchange.markets:
            return "Not listed on Binance"

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        if len(ohlcv) < 50:
            return "Low data"

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd_diff()
        df["ema20"] = ta.trend.EMAIndicator(df["close"], 20).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], 50).ema_indicator()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Signal rules: oversold + bullish cross + trend
        if last["rsi"] < 30 and prev["macd"] < 0 and last["macd"] > 0 and last["ema20"] > last["ema50"]:
            return f"📈 BUY | RSI:{last['rsi']:.1f} MACD:↗️"
        elif last["rsi"] > 70 and prev["macd"] > 0 and last["macd"] < 0 and last["ema20"] < last["ema50"]:
            return f"📉 SELL | RSI:{last['rsi']:.1f} MACD:↘️"
        else:
            return f"⏳ HOLD | RSI:{last['rsi']:.1f}"
    except ccxt.NetworkError as e:
        logger.warning("Network error fetching %s: %s", symbol, e)
        return "Network error"
    except ccxt.ExchangeError as e:
        logger.warning("Exchange error fetching %s: %s", symbol, e)
        return "Exchange error"
    except Exception as e:
        logger.exception("Unexpected error fetching %s: %s", symbol, e)
        return "Data error"


def get_news(coin="BTC"):
    if not CRYPTO_PANIC_KEY:
        return "News unavailable (no API key configured)"
    try:
        url = (
            f"https://api.cryptopanic.com/api/v1/posts/"
            f"?auth_token={CRYPTO_PANIC_KEY}&currencies={coin}&public=true"
        )
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        headlines = [f"📰 {x['title'][:70]}..." for x in data.get("results", [])[:3]]
        return "\n".join(headlines) if headlines else "No recent news"
    except requests.RequestException as e:
        logger.warning("News API error for %s: %s", coin, e)
        return "News API error"
    except (KeyError, ValueError) as e:
        logger.warning("News API parse error for %s: %s", coin, e)
        return "News API error"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🚀 Top 40 Non-Stablecoin TA Bot

Commands:
/signals - Scan all 40 coins
/ta BTC - Single coin TA
/news BTC - Latest news
/oversold - RSI < 35 watchlist

⚠️ Not financial advice. DYOR."""
    await update.message.reply_text(text)


async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Scanning 40 coins... ~25s")
    buys, sells = [], []

    for sym in TOP_40:
        signal = get_ta_signal(sym)
        coin = sym.split("/")[0]
        if "BUY" in signal:
            buys.append(f"{coin} {signal}")
        elif "SELL" in signal:
            sells.append(f"{coin} {signal}")
        await asyncio.sleep(0.25)  # Rate limit safety

    result = f"📊 Top 40 Signals | {datetime.now().strftime('%H:%M WAT')}\n\n"
    result += "🟢 BUY:\n" + ("\n".join(buys[:12]) if buys else "None") + "\n\n"
    result += "🔴 SELL:\n" + ("\n".join(sells[:12]) if sells else "None") + "\n\n"
    result += "⚠️ Not financial advice."

    await msg.edit_text(result[:4096])


async def ta_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /ta BTC")
    coin = context.args[0].upper() + "/USDT"
    signal = get_ta_signal(coin)
    news = get_news(coin.split("/")[0])
    await update.message.reply_text(f"{coin}\n{signal}\n\n{news}")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = context.args[0].upper() if context.args else "BTC"
    news = get_news(coin)
    await update.message.reply_text(f"📰 {coin} News\n\n{news}")


async def oversold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Checking RSI...")
    ensure_markets_loaded()
    oversold_list = []

    for sym in TOP_40:
        try:
            ohlcv = exchange.fetch_ohlcv(sym, "1h", limit=50)
            df = pd.DataFrame(ohlcv, columns=["ts", "o", "h", "l", "c", "v"])
            rsi = ta.momentum.RSIIndicator(df["c"], 14).rsi().iloc[-1]
            if rsi < 35:
                oversold_list.append(f"{sym.split('/')[0]}: {rsi:.1f}")
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning("RSI check failed for %s: %s", sym, e)
        await asyncio.sleep(0.2)

    text = "📉 Oversold RSI<35\n" + "\n".join(oversold_list) if oversold_list else "No coins oversold"
    await msg.edit_text(text)


async def auto_post(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    buys, sells = [], []
    for sym in TOP_40:
        signal = get_ta_signal(sym)
        coin = sym.split("/")[0]
        if "BUY" in signal:
            buys.append(coin)
        elif "SELL" in signal:
            sells.append(coin)
        await asyncio.sleep(0.25)

    text = (
        f"⏰ Hourly Scan {datetime.now().strftime('%H:%M')}\n"
        f"🟢 {', '.join(buys[:5]) if buys else 'None'}\n"
        f"🔴 {', '.join(sells[:5]) if sells else 'None'}"
    )
    await context.bot.send_message(chat_id, text)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("ta", ta_single))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("oversold", oversold))

    # Auto post every hour. Uncomment and set YOUR_CHAT_ID to your channel/group ID.
    # app.job_queue.run_repeating(auto_post, interval=3600, first=10, chat_id=YOUR_CHAT_ID)

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
