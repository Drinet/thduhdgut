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
BLACKLIST = ['STETH', 'WBTC', 'USDG', 'TBTC', 'TUSD', 'NFT', 'USDT', 'USDC', 'DAI', 'FDUSD', 'WETH']

ex = ccxt.binance({'enableRateLimit': True})

def log(msg):
    print(msg, flush=True)

def get_pivots(df, window=3):
    """Detects local price peaks and troughs."""
    df = df.copy()
    df['is_high'] = df['high'] == df['high'].rolling(window=window*2+1, center=True).max()
    df['is_low'] = df['low'] == df['low'].rolling(window=window*2+1, center=True).min()
    return df[df['is_high']], df[df['is_low']]

def detect_trendline(df, side='upper'):
    """Draws a line through the most recent significant price points."""
    highs, lows = get_pivots(df)
    points = highs if side == 'upper' else lows
    prices = points['high'] if side == 'upper' else points['low']
    
    if len(points) < 2:
        return None, None
    
    # Use the last two pivot points
    p1_idx, p1_y = points.index[-2], prices.values[-2]
    p2_idx, p2_y = points.index[-1], prices.values[-1]
    
    slope = (p2_y - p1_y) / (p2_idx - p1_idx)
    intercept = p2_y - (slope * p2_idx)
    
    full_x = np.arange(len(df))
    line = slope * full_x + intercept
    return line, slope

def send_alert(title, df, coin, tf, line):
    """Sends the pattern chart to Discord."""
    df_plot = df.tail(120).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    
    # Draw the trendline on the chart
    ap = [mpf.make_addplot(line[-120:], color='white', width=1.5, linestyle='--')]
    
    buf = io.BytesIO()
    mpf.plot(df_plot, type='candle', style='charles', addplot=ap, 
             savefig=dict(fname=buf, format='png'), axisoff=True)
    buf.seek(0)
    
    msg = f"**{title}**\n🪙 **${coin}**\n📅 Timeframe: {tf}\n💸 Price: {df['close'].iloc[-1]}"
    
    requests.post(DISCORD_WEBHOOK, 
                  files={"files[0]": (f"{coin}.png", buf, "image/png")},
                  data={"payload_json": json.dumps({"content": msg})})

def main():
    log("🚀 Scanning for breakout patterns...")
    try:
        # Get top 150 coins by market cap
        coins = requests.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=150").json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except: return

    for coin in symbols:
        for tf in ['1h', '4h']:
            try:
                bars = ex.fetch_ohlcv(f"{coin}/USDT", timeframe=tf, limit=200)
                df = pd.DataFrame(bars, columns=['date','open','high','low','close','vol'])
                
                # Check for Breakout ABOVE Resistance
                u_line, _ = detect_trendline(df, 'upper')
                if u_line is not None and df['close'].iloc[-1] > u_line[-1]:
                    log(f"FOUND: {coin} Long")
                    send_alert("🚀 **Long trade**", df, coin, tf, u_line)
                    break 
                
                # Check for Breakout BELOW Support
                l_line, _ = detect_trendline(df, 'lower')
                if l_line is not None and df['close'].iloc[-1] < l_line[-1]:
                    log(f"FOUND: {coin} Short")
                    send_alert("📉 **Short trade**", df, coin, tf, l_line)
                    break
            except: continue
        time.sleep(0.1) # Avoid rate limits
    log("🏁 Done.")

if __name__ == "__main__":
    main()
