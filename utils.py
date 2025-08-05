
def calculate_trade_score(rsi, wick_percent, news_bias, trend_vwap):
    score = 0
    if rsi < 30 or rsi > 70:
        score += 1
    if wick_percent > 20:
        score += 1
    if trend_vwap:
        score += 1
    if news_bias in ['bullish', 'bearish']:
        score += 1
    return score

def determine_tp_sl(entry_price, direction, sl_points=15, rr=2):
    if direction == 'long':
        sl = entry_price - sl_points
        tp = entry_price + sl_points * rr
    else:
        sl = entry_price + sl_points
        tp = entry_price - sl_points * rr
    return tp, sl

def get_confidence(score):
    if score >= 4:
        return "🔥 High"
    elif score == 3:
        return "✅ Medium"
    else:
        return "⚠️ Low"

def detect_engulfing(open_prev, close_prev, open_curr, close_curr):
    return (close_prev < open_prev and close_curr > open_curr and close_curr > open_prev and open_curr < close_prev) or            (close_prev > open_prev and close_curr < open_curr and close_curr < open_prev and open_curr > close_prev)
