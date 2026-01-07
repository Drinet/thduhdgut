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
BLACKLIST = ['STETH', 'WBTC', 'USDG', 'TBTC', 'TUSD', 'NFT', 'USDT', 'USDC', 'DAI', 'FDUSD', 'WETH']

ex = ccxt.binance({'enableRateLimit': True})

def log(msg):
    print(msg, flush=True)

def get_pivots(df, window=3):
    df = df.copy()
    # Find local peaks and troughs
    df['is_high'] = df['high'] == df['high'].rolling(window=window*2+1, center=True).max()
    df['is_low'] = df['low'] == df['low'].rolling(window=window*2+1, center=True).min()
    return df[df['is_high']], df[df['is_low']]

def detect_fuzzy_trendline(df, side='upper'):
    highs, lows = get_pivots(df)
    points = highs if side == 'upper' else lows
    
    if len(points) < 3: # Need at least 3 points for a reliable regression
        return None, None
    
    # Take the last 3-5 pivot points to find the average trend
    recent_pivots = points.tail(5)
    x = recent_pivots.index.values
    y = recent_pivots['high'].values if side == 'upper' else recent_pivots['low'].values
    
    slope, intercept, r_value, p_value, std_err = linregress(x, y)
    
    # Project the line across the whole dataframe
    full_x = np.arange(len(df))
    line = slope * full_x + intercept
    return line, slope

def send_trade(content, df, coin, tf, line):
    # Charting setup
    df_plot = df.tail(120).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    line_seg = line[-120:]
    ap = [mpf.make_addplot(line_seg, color='white', width=1, linestyle='--')]
    
    buf = io.BytesIO()
    mpf.plot(df_plot, type='candle', style='charles', addplot=ap, 
             savefig=dict(fname=buf, format='png'), axisoff=True)
    buf.seek(0)
    
    # Prepare Trade Text based on instructions
    price = df['close'].iloc[-1]
    sl = price * 0.98
    tp1, tp2, tp3 = price * 1.015, price * 1.03, price * 1.05
    
    trade_text = (f"**{content}**\n"
                  f"🪙 **${coin}** ({tf})\n"
                  f"Entry: {price:.4f}\n"
                  f"🚫 SL: {sl:.4f}\n"
                  f"🎯 TP1: {tp1:.4f} | TP2: {tp2:.4f} | TP3: {tp3:.4f}")
    
    requests.post(DISCORD_WEBHOOK, 
                  files={"files[0]": (f"{coin}.png", buf, "image/png")},
                  data={"payload_json": json.dumps({"content": trade_text})})

def main():
    log("Checking Top 100 Coins for Fuzzy Breakouts...")
    try:
        coins = requests.get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=100").json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except: return

    for coin in symbols:
        ticker = f"{coin}/USDT"
        for tf in ['1h', '4h']:
            try:
                bars = ex.fetch_ohlcv(ticker, timeframe=tf, limit=200)
                df = pd.DataFrame(bars, columns=['date','open','high','low','close','vol'])
                
                # Check BULLISH
                u_line, _ = detect_fuzzy_trendline(df, 'upper')
                if u_line is not None and df['close'].iloc[-1] > u_line[-1]:
                    log(f"MATCH: {coin} Long")
                    send_trade("🚀 **Long Trade**", df, coin, tf, u_line)
                    break
                
                # Check BEARISH
                l_line, _ = detect_fuzzy_trendline(df, 'lower')
                if l_line is not None and df['close'].iloc[-1] < l_line[-1]:
                    log(f"MATCH: {coin} Short")
                    send_trade("📉 **Short Trade**", df, coin, tf, l_line)
                    break
            except: continue
        time.sleep(0.2)

if __name__ == "__main__":
    main()
