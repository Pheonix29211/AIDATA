# ai_core.py
# Reward shaping + post-loss adaptation (“dopamine TP hunter”)
import os, json, time, math, threading
from collections import deque

# Persisted state (set AI_STATE_FILE=/data/ai_state.json on Render)
STATE_FILE    = os.getenv("AI_STATE_FILE", "/data/ai_state.json")
# Scale PnL to your TP2 size so rewards match your $ targets (e.g., 1200)
PAYOUT_SCALE  = float(os.getenv("PAYOUT_SCALE", "1200"))
# Initial exploration (can decay after wins)
INIT_EXPLORE  = float(os.getenv("AI_EXPLORATION", "0.05"))

_lock = threading.Lock()

# simple regime memories: rolling average reward per regime
_model_memory = {
    "trend": deque(maxlen=1000),
    "range": deque(maxlen=1000),
    "spike": deque(maxlen=1000)
}

# runtime meta-state (persists across restarts)
_state = {
    "sl_streak": 0,
    "last_outcome_ts": 0,
    "exploration": INIT_EXPLORE,
    "caution_multiplier": 1.0,  # >1 => stricter gating for a while
}

def _load_state():
    try:
        with open(STATE_FILE, "r") as f:
            _state.update(json.load(f))
    except Exception:
        pass

def _save_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_state, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass

_load_state()

def score(features: dict, regime: str):
    """
    Returns (p, exploration). Keep features lightweight and numeric:
      ema_spread (0..1), ema_slope (−1..1), htf_align (0..1), vol_norm (0..1)
    """
    hist = _model_memory.get(regime) or []
    prior = (sum(hist) / len(hist)) if hist else 0.55

    ema_spread = float(features.get("ema_spread", 0.0))
    ema_slope  = float(features.get("ema_slope", 0.0))
    htf_align  = float(features.get("htf_align", 0.0))
    vol_norm   = float(features.get("vol_norm", 0.0))

    base = prior + 0.10*ema_spread + 0.06*ema_slope + 0.05*htf_align + 0.02*vol_norm
    # caution after losses makes it a bit harder to fire
    base -= 0.05 * max(0.0, _state.get("caution_multiplier", 1.0) - 1.0)

    p = max(0.0, min(1.0, base))
    return p, _state.get("exploration", INIT_EXPLORE)

def online_update(features: dict, regime: str, reward: float):
    # lightweight bandit-style update
    try:
        _model_memory.setdefault(regime, deque(maxlen=1000)).append(float(reward))
    except Exception:
        pass

def compute_reward(*,
                   outcome: str, pnl: float, bars_to_exit: int,
                   tp2_hit: bool, tp1_hit: bool,
                   sl_expanded: bool, sl_dollars: float, sl_cap_base: float,
                   trailing_respected: bool, momentum_aligned_bars: int,
                   duplicate_entry: bool) -> float:
    """
    Translate trade outcome into a shaped reward:
      - normalize by PAYOUT_SCALE (≈ TP2) so $ aligns with [0..1]
      - bonus for momentum alignment, discipline; penalties for SL, churn
    """
    base = max(0.0, min(1.0, pnl / max(1.0, PAYOUT_SCALE)))
    if outcome == "TP2": base *= 1.35
    elif outcome == "TP1": base *= 1.00
    elif outcome == "SL":  base = 0.0

    time_bonus = math.exp(-0.03 * max(0, bars_to_exit))  # faster wins preferred
    risk_bonus = 0.10 if (outcome != "SL" and sl_dollars <= sl_cap_base) else 0.0
    if sl_expanded and outcome != "TP2":
        risk_bonus -= 0.06

    momo_bonus = min(0.20, 0.012 * max(0, momentum_aligned_bars))
    churn_penalty = -0.08 if duplicate_entry else 0.0

    sl_penalty = 0.0
    if outcome == "SL":
        size_factor = min(1.3, sl_dollars / max(1.0, sl_cap_base))
        sl_penalty = -0.42 * size_factor
        if sl_expanded:
            sl_penalty -= 0.12
        streak = int(_state.get("sl_streak", 0))
        if streak >= 1:
            sl_penalty *= min(1.6, 1.0 + 0.25*streak)

    missed_tp_penalty = 0.0
    if outcome not in ("TP2", "SL") and tp2_hit and trailing_respected:
        missed_tp_penalty = -0.22  # exited early while TP2 was reachable

    reward = base*time_bonus + risk_bonus + momo_bonus + churn_penalty + sl_penalty + missed_tp_penalty
    return max(-0.8, min(1.35, reward))

def register_outcome(outcome: str):
    """Adjust ‘caution’ & exploration after each trade result."""
    now = time.time()
    with _lock:
        _state["last_outcome_ts"] = now
        if outcome == "SL":
            _state["sl_streak"] = int(_state.get("sl_streak", 0)) + 1
            _state["caution_multiplier"] = min(1.8, 1.0 + 0.25 * _state["sl_streak"])
            _state["exploration"] = min(0.25, _state.get("exploration", INIT_EXPLORE) + 0.03)
        else:
            _state["sl_streak"] = 0
            if outcome == "TP2":
                _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.35)
                _state["exploration"] = max(0.04, _state.get("exploration", INIT_EXPLORE) - 0.02)
            elif outcome == "TP1":
                _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.20)
                _state["exploration"] = max(0.045, _state.get("exploration", INIT_EXPLORE) - 0.01)
            else:
                _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.05)
                _state["exploration"] = max(0.04, _state.get("exploration", INIT_EXPLORE) - 0.005)
        _save_state()

def ai_status():
    return {
        "sl_streak": int(_state.get("sl_streak", 0)),
        "caution": round(float(_state.get("caution_multiplier", 1.0)), 2),
        "explore": round(float(_state.get("exploration", INIT_EXPLORE)), 3),
        "state_file": STATE_FILE,
        "payout_scale": PAYOUT_SCALE
    }
