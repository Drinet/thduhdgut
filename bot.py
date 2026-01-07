import ccxt
import pandas as pd
import numpy as np
import requests
import os
import json
import time
import mplfinance as mpf
import io
from scipy.stats import linregress

# --- CONFIG ---
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL')
DB_FILE = "trade_history.json"
BLACKLIST = ['STETH', 'WBTC', 'USDG', 'TBTC', 'TUSD', 'NFT', 'USDT', 'USDC', 'DAI', 'FDUSD', 'WETH']

EXCHANGES = {
    "binance": ccxt.binance({'enableRateLimit': True}),
    "bybit": ccxt.bybit({'enableRateLimit': True})
}

DARK_STYLE = mpf.make_mpf_style(
    base_mpf_style='binance', 
    facecolor='#000000', gridcolor='#1A1A1A', figcolor='#000000',      
    rc={'axes.labelsize': 0, 'xtick.labelsize': 0, 'ytick.labelsize': 0,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'axes.spines.bottom': False},
    marketcolors=mpf.make_marketcolors(up='#00FF00', down='#FF0000', inherit=True)
)

def get_pivots(df, window=3):
    """Finds local peaks and troughs."""
    # Rolling window to find local max/min
    df['is_high'] = df['high'] == df['high'].rolling(window=window*2+1, center=True).max()
    df['is_low'] = df['low'] == df['low'].rolling(window=window*2+1, center=True).min()
    return df[df['is_high']], df[df['is_low']]

def detect_trendline(df, side='upper'):
    """Calculates a trendline requiring only 2 points for higher frequency."""
    highs, lows = get_pivots(df)
    points = highs if side == 'upper' else lows
    prices = points['high'] if side == 'upper' else points['low']
    
    # CHANGED: Now only requires 2 touches instead of 3
    if len(points) < 2:
        return None, None
    
    x_coords = points.index
    y_coords = prices.values
    
    # We use the last two significant pivots to draw the 'current' trendline
    p1_x, p1_y = x_coords[-2], y_coords[-2]
    p2_x, p2_y = x_coords[-1], y_coords[-1]
    
    slope = (p2_y - p1_y) / (p2_x - p1_x)
    intercept = p2_y - (slope * p2_x)
    
    full_x = np.arange(len(df))
    line = slope * full_x + intercept
    return line, slope

def send_discord_with_chart(content, df, coin, timeframe, line_data):
    # Zoomed out to 120 candles for context
    df_plot = df.tail(120).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    
    ap = []
    if line_data is not None:
        line_segment = line_data[-120:]
        ap.append(mpf.make_addplot(line_segment, color='#FFFFFF', width=1.2, linestyle='--'))

    buf = io.BytesIO()
    mpf.plot(df_plot, type='candle', style=DARK_STYLE, addplot=ap,
             figsize=(12, 6), savefig=dict(fname=buf, format='png', bbox_inches='tight'),
             axisoff=True, volume=False)
    
    buf.seek(0)
    payload = {"content": content}
    files = {"payload_json": (None, json.dumps(payload)), "files[0]": (f"{coin}.png", buf, "image/png")}
    requests.post(DISCORD_WEBHOOK, files=files)

def main():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f: json.dump({"bias": "BULLISH"}, f)
    
    with open(DB_FILE, 'r') as f: db = json.load(f)
    bias = db.get("bias", "BULLISH")
    
    print(f"Starting scan. Global Bias: {bias}")
    
    timeframes = ['1h', '4h']
    
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        coins = requests.get(url, params={'vs_currency': 'usd', 'per_page': 100}).json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except Exception as e:
        print(f"Error fetching coins: {e}")
        return

    for coin in symbols:
        for tf in timeframes:
            for name, ex in EXCHANGES.items():
                try:
                    bars = ex.fetch_ohlcv(f"{coin}/USDT", timeframe=tf, limit=200)
                    if not bars: continue
                    df = pd.DataFrame(bars, columns=['date','open','high','low','close','vol'])
                    
                    if bias == "BULLISH":
                        line, slope = detect_trendline(df, 'upper')
                        if line is not None:
                            # Breakout: Cross from below the line to above the line
                            if df['close'].iloc[-2] < line[-2] and df['close'].iloc[-1] > line[-1]:
                                print(f"MATCH: {coin} breakout on {tf}")
                                msg = f"🚀 **TRENDLINE BREAKOUT**\n🪙 **${coin}**\n📅 **Timeframe:** {tf}\n✨ 2-Point Resistance Broken"
                                send_discord_with_chart(msg, df, coin, tf, line)
                                break
                    
                    elif bias == "BEARISH":
                        line, slope = detect_trendline(df, 'lower')
                        if line is not None:
                            # Breakdown: Cross from above the line to below the line
                            if df['close'].iloc[-2] > line[-2] and df['close'].iloc[-1] < line[-1]:
                                print(f"MATCH: {coin} breakdown on {tf}")
                                msg = f"📉 **TRENDLINE BREAKDOWN**\n🪙 **${coin}**\n📅 **Timeframe:** {tf}\n✨ 2-Point Support Lost"
                                send_discord_with_chart(msg, df, coin, tf, line)
                                break
                except: continue
            time.sleep(0.3)

if __name__ == "__main__":
    main()
