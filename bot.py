import ccxt
import pandas as pd
import numpy as np
import requests
import os
import json
import time
import mplfinance as mpf
import io

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

def get_pivots(df, window=5):
    df = df.copy()
    # Identifies local peaks and troughs
    df['is_high'] = df['high'] == df['high'].rolling(window=window*2+1, center=True).max()
    df['is_low'] = df['low'] == df['low'].rolling(window=window*2+1, center=True).min()
    return df[df['is_high']], df[df['is_low']]

def detect_trendline(df, side='upper'):
    highs, lows = get_pivots(df)
    points = highs if side == 'upper' else lows
    prices = points['high'] if side == 'upper' else points['low']
    
    if len(points) < 2:
        return None, None
    
    # Draw line through the two most significant recent pivots
    p1_idx, p1_y = points.index[-2], prices.values[-2]
    p2_idx, p2_y = points.index[-1], prices.values[-1]
    
    slope = (p2_y - p1_y) / (p2_idx - p1_idx)
    intercept = p2_y - (slope * p2_idx)
    
    full_x = np.arange(len(df))
    line = slope * full_x + intercept
    return line, slope

def send_discord_with_chart(content, df, coin, timeframe, line_data):
    # Zoom out to 150 candles for broad pattern visibility
    df_plot = df.tail(150).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    
    ap = []
    if line_data is not None:
        line_segment = line_data[-150:]
        ap.append(mpf.make_addplot(line_segment, color='#FFFFFF', width=1.5, linestyle='--'))

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
    
    print(f"--- SCANNING TOP 150 COINS | BIAS: {bias} ---")
    
    timeframes = ['1h', '4h', '1d']
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        coins = requests.get(url, params={'vs_currency': 'usd', 'per_page': 150}).json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except: return

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
                            # If price is currently above the resistance trendline 
                            # and was below it at some point in the last 30 candles
                            is_above = df['close'].iloc[-1] > line[-1]
                            was_below = (df['close'].iloc[-35:-1] < line[-35:-1]).any()
                            
                            if is_above and was_below:
                                print(f"MATCH: {coin} is currently above resistance on {tf}")
                                msg = f"🚀 **BULLISH TREND**\n🪙 **${coin}**\n📅 **TF:** {tf}\n✨ Price holding above broken trendline."
                                send_discord_with_chart(msg, df, coin, tf, line)
                                time.sleep(1.5)
                                break
                                    
                    elif bias == "BEARISH":
                        line, slope = detect_trendline(df, 'lower')
                        if line is not None:
                            is_below = df['close'].iloc[-1] < line[-1]
                            was_above = (df['close'].iloc[-35:-1] > line[-35:-1]).any()
                            
                            if is_below and was_above:
                                print(f"MATCH: {coin} is currently below support on {tf}")
                                msg = f"📉 **BEARISH TREND**\n🪙 **${coin}**\n📅 **TF:** {tf}\n✨ Price holding below broken trendline."
                                send_discord_with_chart(msg, df, coin, tf, line)
                                time.sleep(1.5)
                                break
                except: continue
    print("Scan complete.")

if __name__ == "__main__":
    main()
