import ccxt
import pandas as pd
import numpy as np
import requests
import os
import json
import time
import mplfinance as mpf
import io
import sys

# --- FORCED LOGGING ---
def log(msg):
    print(msg, flush=True)

# --- CONFIG ---
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL')
DB_FILE = "trade_history.json"
BLACKLIST = ['STETH', 'WBTC', 'USDG', 'TBTC', 'TUSD', 'NFT', 'USDT', 'USDC', 'DAI', 'FDUSD', 'WETH']

ex = ccxt.binance({'enableRateLimit': True})

DARK_STYLE = mpf.make_mpf_style(
    base_mpf_style='binance', 
    facecolor='#000000', gridcolor='#1A1A1A', figcolor='#000000',      
    rc={'axes.labelsize': 0, 'xtick.labelsize': 0, 'ytick.labelsize': 0,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'axes.spines.bottom': False},
    marketcolors=mpf.make_marketcolors(up='#00FF00', down='#FF0000', inherit=True)
)

def get_pivots(df, window=3):
    """Detects local peaks/troughs. Smaller window = more patterns found."""
    df = df.copy()
    df['is_high'] = df['high'] == df['high'].rolling(window=window*2+1, center=True).max()
    df['is_low'] = df['low'] == df['low'].rolling(window=window*2+1, center=True).min()
    return df[df['is_high']], df[df['is_low']]

def detect_trendline(df, side='upper'):
    highs, lows = get_pivots(df)
    points = highs if side == 'upper' else lows
    prices = points['high'] if side == 'upper' else points['low']
    
    if len(points) < 2:
        return None, None
    
    # Use last 2 pivots to define line
    p1_idx, p1_y = points.index[-2], prices.values[-2]
    p2_idx, p2_y = points.index[-1], prices.values[-1]
    
    slope = (p2_y - p1_y) / (p2_idx - p1_idx)
    intercept = p2_y - (slope * p2_idx)
    
    full_x = np.arange(len(df))
    line = slope * full_x + intercept
    return line, slope

def send_discord_with_chart(content, df, coin, timeframe, line_data):
    df_plot = df.tail(100).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    ap = []
    if line_data is not None:
        line_segment = line_data[-100:]
        ap.append(mpf.make_addplot(line_segment, color='#FFFFFF', width=1.3, linestyle='--'))

    buf = io.BytesIO()
    mpf.plot(df_plot, type='candle', style=DARK_STYLE, addplot=ap,
             figsize=(12, 6), savefig=dict(fname=buf, format='png', bbox_inches='tight'),
             axisoff=True, volume=False)
    buf.seek(0)
    files = {"payload_json": (None, json.dumps({"content": content})), "files[0]": (f"{coin}.png", buf, "image/png")}
    requests.post(DISCORD_WEBHOOK, files=files)

def main():
    log("🚀 Starting Pattern Scanner...")
    
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f: json.dump({"bias": "BULLISH"}, f)
    with open(DB_FILE, 'r') as f: db = json.load(f)
    bias = db.get("bias", "BULLISH")
    
    log(f"Current Global Bias: {bias}")
    
    try:
        # Check top 200 coins
        url = "https://api.coingecko.com/api/v3/coins/markets"
        coins = requests.get(url, params={'vs_currency': 'usd', 'per_page': 200}).json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except Exception as e:
        log(f"Error: {e}")
        return

    for i, coin in enumerate(symbols):
        ticker = f"{coin}/USDT"
        # Progress log
        if i % 20 == 0: log(f"Scanning progress: {i}/{len(symbols)}...")
            
        for tf in ['1h', '4h']:
            try:
                bars = ex.fetch_ohlcv(ticker, timeframe=tf, limit=150)
                if not bars: continue
                df = pd.DataFrame(bars, columns=['date','open','high','low','close','vol'])
                
                if bias == "BULLISH":
                    line, _ = detect_trendline(df, 'upper')
                    if line is not None:
                        # Success: Current price is at least 0.1% above the resistance line
                        if df['close'].iloc[-1] > (line[-1] * 1.001):
                            log(f"🔥 BULLISH BREAK: {ticker} on {tf}")
                            msg = f"🚀 **LONG**\n🪙 **${coin}**\n📅 **TF:** {tf}\n✨ Trendline Resistance Broken"
                            send_discord_with_chart(msg, df, coin, tf, line)
                            time.sleep(1)
                            break
                
                elif bias == "BEARISH":
                    line, _ = detect_trendline(df, 'lower')
                    if line is not None:
                        # Success: Current price is at least 0.1% below the support line
                        if df['close'].iloc[-1] < (line[-1] * 0.999):
                            log(f"📉 BEARISH BREAK: {ticker} on {tf}")
                            msg = f"📉 **SHORT**\n🪙 **${coin}**\n📅 **TF:** {tf}\n✨ Trendline Support Broken"
                            send_discord_with_chart(msg, df, coin, tf, line)
                            time.sleep(1)
                            break
            except:
                continue
    log("🏁 Scan finished.")

if __name__ == "__main__":
    main()
