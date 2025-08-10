# ai_core.py — tiny online learner (per regime), session-aware
import json, math
from pathlib import Path

STATE_F = Path("ai_state.json")
MEM_F   = Path("ai_memory.json")
REGIMES = ["trend","range","spike"]

def _load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default

def _save_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2))

def _init_state():
    state = _load_json(STATE_F, {})
    for r in REGIMES:
        if r not in state:
            state[r] = {
                "w": {k:0.0 for k in [
                    "ema_slope","ema_spread","vwap_dist","rsi","rsi_slope",
                    "atr_pct","wick_ratio","dist_to_swing","ema_flip_count",
                    "session_asia","session_london","session_ny","session_overlap",
                    "hour_sin","hour_cos","dow_sin","dow_cos"
                ]},
                "bias": 0.0
            }
    _save_json(STATE_F, state)
    mem = _load_json(MEM_F, {"stats":{}})
    _save_json(MEM_F, mem)
    return state, mem

STATE, MEM = _init_state()

def _sigmoid(x):
    if x > 30: return 1.0
    if x < -30: return 0.0
    return 1/(1+math.exp(-x))

def score(features: dict, regime: str):
    if regime not in STATE: _init_state()
    w = STATE[regime]["w"]; b = STATE[regime]["bias"]
    z = sum(w.get(k,0.0)*float(features.get(k,0.0)) for k in w) + b
    return _sigmoid(z), z

def online_update(features: dict, regime: str, label: float, lr: float=0.03, decay: float=1e-5):
    if regime not in STATE: _init_state()
    p, _ = score(features, regime)
    err = (label - p)
    for k in STATE[regime]["w"]:
        x = float(features.get(k,0.0))
        w_old = STATE[regime]["w"][k]
        STATE[regime]["w"][k] = (1 - decay)*w_old + lr*err*x
    STATE[regime]["bias"] = (1 - decay)*STATE[regime]["bias"] + lr*err
    _save_json(STATE_F, STATE)

def log_candle_stats(regime: str, session: str, reward: float):
    key = f"{regime}:{session}"
    s = MEM["stats"].get(key, {"n":0,"sum":0.0})
    s["n"] += 1; s["sum"] += float(reward)
    MEM["stats"][key] = s
    _save_json(MEM_F, MEM)
