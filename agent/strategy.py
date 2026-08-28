from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"

@dataclass
class PreflopConfig:
    short_stack_threshold_ip: float = 18.0
    short_stack_threshold_oop: float = 14.0
    open_base_eq: float = 0.46
    open_not_ip_penalty: float = 0.04
    open_active_player_penalty: float = 0.015
    open_spr_factor: float = 0.02
    open_delta_factor: float = 0.25
    limp_offset: float = 0.03
    min_3bet_equity: float = 0.62
    anti_blunder_call_bb: float = 4.0
    anti_blunder_risk_ratio: float = 0.12

@dataclass
class PostflopConfig:
    cbet_dry_threshold: float = 0.45
    cbet_wet_threshold: float = 0.38
    cbet_wet_factor: float = 0.08
    monster_raise_equity: float = 0.75
    mdf_max_call_pot_ratio: float = 0.35
    multi_street_pressure_base: float = 0.08
    river_heavy_bet_pot_ratio: float = 0.50
    river_heavy_bet_risk_ratio: float = 0.20
    river_hard_equity_floor: float = 0.65

@dataclass
class RiskConfig:
    kelly_fraction_min: float = 0.08
    kelly_fraction_max: float = 0.35
    kelly_fraction_scale: float = 70.0
    max_risk_floor: float = 0.12
    max_risk_cap: float = 0.50
    stack_off_req_floor: float = 0.58
    stack_off_req_cap: float = 0.96

@dataclass
class StrategyProfile:
    name: str = "tag"
    target_vpip: float = 0.30
    vpip_ema_alpha: float = 0.05
    preflop: PreflopConfig = field(default_factory=PreflopConfig)
    postflop: PostflopConfig = field(default_factory=PostflopConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

def load_strategy(name: str = "tag") -> StrategyProfile:
    path = STRATEGIES_DIR / f"{name}.json"
    if not path.exists():
        return StrategyProfile(name=name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return StrategyProfile(
            name=data.get("name", name),
            target_vpip=float(data.get("target_vpip", 0.30)),
            vpip_ema_alpha=float(data.get("vpip_ema_alpha", 0.05)),
            preflop=PreflopConfig(**data.get("preflop", {})),
            postflop=PostflopConfig(**data.get("postflop", {})),
            risk=RiskConfig(**data.get("risk", {})),
        )
    except Exception:
        return StrategyProfile(name=name)