# ai_core.py
# Reward shaping + post-loss adaptation (“dopamine TP hunter”)
import math, json, os, time
from collections import deque

STATE_FILE = os.getenv("AI_STATE_FILE", "ai_state.json")

# regime memories
_model_memory = {"trend": deque(maxlen=500), "range": deque(maxlen=500), "spike": deque(maxlen=500)}

# runtime meta-state (persists)
_state = {
    "sl_streak": 0,
    "last_outcome_ts": 0,
    "exploration": 0.05,        # small exploration for research
    "caution_multiplier": 1.0,  # >1 => stricter gating for a while
}

def _load_state():
    try:
        if os.path.exists(STATE_FILE):
            _state.update(json.load(open(STATE_FILE, "r")))
    except Exception:
        pass

def _save_state():
    try:
        json.dump(_state, open(STATE_FILE, "w"))
    except Exception:
        pass

_load_state()

def score(features: dict, regime: str):
    """Simple scorer using regime reward prior + a couple of features.
       Replace with your real model later; API stays stable."""
    hist = _model_memory.get(regime, [])
    prior = (sum(hist)/len(hist)) if hist else 0.55
    base = prior + 0.10*features.get("ema_spread", 0.0) + 0.05*features.get("ema_slope", 0.0)
    # caution mode: require a bit more confidence after losses
    base -= 0.05 * max(0.0, _state.get("caution_multiplier", 1.0) - 1.0)
    p = max(0.0, min(1.0, base))
    return p, _state.get("exploration", 0.05)

def online_update(features: dict, regime: str, reward: float):
    _model_memory.setdefault(regime, deque(maxlen=500)).append(float(reward))

def compute_reward(*,
                   outcome: str, pnl: float, bars_to_exit: int,
                   tp2_hit: bool, tp1_hit: bool,
                   sl_expanded: bool, sl_dollars: float, sl_cap_base: float,
                   trailing_respected: bool, momentum_aligned_bars: int,
                   duplicate_entry: bool) -> float:
    # Core “dopamine” on realized profit; bigger for TP2
    base = max(0.0, min(1.0, pnl / 1000.0))
    if outcome == "TP2": base *= 1.35
    elif outcome == "TP1": base *= 1.00
    elif outcome == "SL":  base = 0.0

    # Prefer faster wins
    k = 0.03
    time_bonus = math.exp(-k * max(0, bars_to_exit))

    # Discipline + momentum
    risk_bonus = 0.10 if (outcome != "SL" and sl_dollars <= sl_cap_base) else 0.0
    if sl_expanded and outcome != "TP2":
        risk_bonus -= 0.06
    momo_bonus = min(0.18, 0.012 * max(0, momentum_aligned_bars))

    churn_penalty = -0.08 if duplicate_entry else 0.0

    # Heavier “SL pain”, scaled by size and streak
    sl_penalty = 0.0
    if outcome == "SL":
        size_factor = min(1.3, sl_dollars / max(1.0, sl_cap_base))
        sl_penalty = -0.42 * size_factor
        if sl_expanded:
            sl_penalty -= 0.12
        streak = _state.get("sl_streak", 0)
        if streak >= 1:
            sl_penalty *= min(1.6, 1.0 + 0.25*streak)

    # Missed TP penalty (exited early but TP2 would’ve hit)
    missed_tp_penalty = 0.0
    if outcome not in ("TP2", "SL") and tp2_hit and trailing_respected:
        missed_tp_penalty = -0.22

    reward = base * time_bonus + risk_bonus + momo_bonus + churn_penalty + sl_penalty + missed_tp_penalty
    return max(-0.8, min(1.35, reward))

def register_outcome(outcome: str):
    """Call when a trade closes. Drives ‘try harder’ mode after SL."""
    now = time.time()
    _state["last_outcome_ts"] = now

    if outcome == "SL":
        _state["sl_streak"] = int(_state.get("sl_streak", 0)) + 1
        _state["caution_multiplier"] = min(1.8, 1.0 + 0.25 * _state["sl_streak"])
        _state["exploration"] = min(0.25, _state.get("exploration", 0.05) + 0.03)
    else:
        if outcome == "TP2":
            _state["sl_streak"] = 0
            _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.35)
            _state["exploration"] = max(0.04, _state.get("exploration", 0.05) - 0.02)
        elif outcome == "TP1":
            _state["sl_streak"] = 0
            _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.20)
            _state["exploration"] = max(0.045, _state.get("exploration", 0.05) - 0.01)
        else:
            _state["caution_multiplier"] = max(1.0, _state.get("caution_multiplier", 1.0) - 0.05)
            _state["exploration"] = max(0.04, _state.get("exploration", 0.05) - 0.005)

    _save_state()
