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
    "bybit": ccxt.bybit({'enableRateLimit': True}),
    "gateio": ccxt.gateio({'enableRateLimit': True})
}

DARK_STYLE = mpf.make_mpf_style(
    base_mpf_style='binance', 
    facecolor='#000000',     
    gridcolor='#000000',     
    figcolor='#000000',      
    rc={
        'axes.labelsize': 0, 'xtick.labelsize': 0, 'ytick.labelsize': 0,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'axes.spines.bottom': False
    },
    marketcolors=mpf.make_marketcolors(up='#00FF00', down='#FF0000', inherit=True)
)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {"bias": "BULLISH", "last_seen": []}

def save_db(db):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=4)

def find_trendline(data, type='upper'):
    """Calculates the best fit trendline for resistance or support."""
    y = data.values
    x = np.arange(len(y))
    if type == 'upper':
        # Resistance: connect local highs
        res = []
        for i in range(1, len(y)-1):
            if y[i] > y[i-1] and y[i] > y[i+1]: res.append((x[i], y[i]))
    else:
        # Support: connect local lows
        res = []
        for i in range(1, len(y)-1):
            if y[i] < y[i-1] and y[i] < y[i+1]: res.append((x[i], y[i]))
            
    if len(res) < 2: return None, None
    
    # Use the last two major pivots to draw the current trendline
    p1, p2 = res[-2], res[-1]
    slope = (p2[1] - p1[1]) / (p2[0] - p1[0])
    intercept = p2[1] - slope * p2[0]
    
    line = slope * x + intercept
    return line, slope

def send_discord_with_chart(content, df, coin, line_data):
    df_plot = df.tail(60).copy()
    df_plot.index = pd.to_datetime(df_plot['date'], unit='ms')
    
    # Prepare trendline for plotting
    ap = []
    if line_data is not None:
        # Align trendline to the plot window
        line_segment = line_data[-60:]
        ap.append(mpf.make_addplot(line_segment, color='#FFFFFF', width=1.5, linestyle='--'))

    buf = io.BytesIO()
    mpf.plot(df_plot, type='candle', style=DARK_STYLE, addplot=ap,
             figsize=(10, 5), savefig=dict(fname=buf, format='png', bbox_inches='tight'),
             axisoff=True, volume=False)
    
    buf.seek(0)
    payload = {"content": content}
    files = {"payload_json": (None, json.dumps(payload)), "files[0]": (f"{coin}.png", buf, "image/png")}
    requests.post(DISCORD_WEBHOOK, files=files)

def get_ohlcv(symbol, timeframe):
    for name, ex in EXCHANGES.items():
        try:
            pair = f"{symbol}/USDT"
            bars = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=150)
            if bars and len(bars) >= 100:
                return bars, pair
        except: continue
    return None, None

def main():
    db = load_db()
    bias = db.get("bias", "BULLISH")
    
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        coins = requests.get(url, params={'vs_currency': 'usd', 'per_page': 100}).json()
        symbols = [c['symbol'].upper() for c in coins if c['symbol'].upper() not in BLACKLIST]
    except: return

    for coin in symbols:
        tf = '4h'
        bars, pair = get_ohlcv(coin, tf)
        if not bars: continue

        df = pd.DataFrame(bars, columns=['date','open','high','low','close','vol'])
        
        # Detection Logic
        if bias == "BULLISH":
            line, slope = find_trendline(df['high'], 'upper')
            if line is not None and df['close'].iloc[-2] < line[-2] and df['close'].iloc[-1] > line[-1]:
                # Pattern Breakout Found
                msg = f"🚀 **LONG BREAKOUT**\n🪙 **${coin}**\nTrendline Resistance Broken. Bullish Momentum."
                send_discord_with_chart(msg, df, coin, line)
                time.sleep(2) # Avoid rate limits
        
        elif bias == "BEARISH":
            line, slope = find_trendline(df['low'], 'lower')
            if line is not None and df['close'].iloc[-2] > line[-2] and df['close'].iloc[-1] < line[-1]:
                # Pattern Breakdown Found
                msg = f"📉 **SHORT BREAKDOWN**\n🪙 **${coin}**\nTrendline Support Lost. Bearish Momentum."
                send_discord_with_chart(msg, df, coin, line)
                time.sleep(2)

    save_db(db)

if __name__ == "__main__":
    main()
