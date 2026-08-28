from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class PlayerStats:
    player_id: str
    player_name: str = ""
    hands: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0
    three_bet_hands: int = 0
    faced_three_bet: int = 0
    folded_to_three_bet: int = 0
    postflop_bets: int = 0
    postflop_raises: int = 0
    postflop_calls: int = 0
    postflop_folds: int = 0
    faced_cbet: int = 0
    folded_to_cbet: int = 0

    @property
    def observed_vpip(self) -> float:
        return (self.vpip_hands / self.hands) if self.hands > 0 else 0.24

    @property
    def observed_pfr(self) -> float:
        return (self.pfr_hands / self.hands) if self.hands > 0 else 0.16

    @property
    def observed_af(self) -> float:
        calls = max(self.postflop_calls, 1)
        return (self.postflop_bets + self.postflop_raises) / calls

    @property
    def observed_fold_to_cbet(self) -> float:
        return (self.folded_to_cbet / self.faced_cbet) if self.faced_cbet > 0 else 0.50

class OpponentTracker:
    def __init__(self, shrinkage_k: float = 20.0, min_sample_gate: int = 25):
        self.stats: Dict[str, PlayerStats] = {}
        self.shrinkage_k = shrinkage_k
        self.min_sample_gate = min_sample_gate

        self.pool_total_hands: int = 0
        self.pool_vpip_hands: int = 0
        self.pool_pfr_hands: int = 0
        self.pool_pf_bets_raises: int = 0
        self.pool_pf_calls: int = 0
        self.pool_faced_cbet: int = 0
        self.pool_folded_cbet: int = 0

    @property
    def pool_vpip(self) -> float:
        return (self.pool_vpip_hands / self.pool_total_hands) if self.pool_total_hands > 0 else 0.24

    @property
    def pool_pfr(self) -> float:
        return (self.pool_pfr_hands / self.pool_total_hands) if self.pool_total_hands > 0 else 0.16

    @property
    def pool_af(self) -> float:
        calls = max(self.pool_pf_calls, 1)
        return (self.pool_pf_bets_raises / calls) if self.pool_pf_calls > 0 else 1.5

    @property
    def pool_fold_to_cbet(self) -> float:
        return (self.pool_folded_cbet / self.pool_faced_cbet) if self.pool_faced_cbet > 0 else 0.50

    def get_or_create(self, player_id: str, player_name: str = "") -> PlayerStats:
        if player_id not in self.stats:
            self.stats[player_id] = PlayerStats(player_id=player_id, player_name=player_name)
        if player_name and not self.stats[player_id].player_name:
            self.stats[player_id].player_name = player_name
        return self.stats[player_id]

    def record_hand_actions(self, player_id: str, player_name: str, actions: list[dict]):
        if not player_id:
            return
        ps = self.get_or_create(player_id, player_name)
        ps.hands += 1
        self.pool_total_hands += 1

        is_pfr = False
        is_vpip = False
        is_3bet = False

        for act_info in actions:
            street = str(act_info.get("street", "")).lower()
            act = str(act_info.get("action", "")).lower()

            if street in ("preflop", ""):
                if act in ("call", "bet", "raise", "all-in", "all_in"):
                    is_vpip = True
                if act in ("raise", "bet"):
                    is_pfr = True
                if act == "raise" and act_info.get("raise_count", 1) >= 2:
                    is_3bet = True
            else:
                if act == "bet":
                    ps.postflop_bets += 1
                    self.pool_pf_bets_raises += 1
                elif act == "raise":
                    ps.postflop_raises += 1
                    self.pool_pf_bets_raises += 1
                elif act == "call":
                    ps.postflop_calls += 1
                    self.pool_pf_calls += 1
                elif act == "fold":
                    ps.postflop_folds += 1

                if act_info.get("facing_cbet"):
                    ps.faced_cbet += 1
                    self.pool_faced_cbet += 1
                    if act == "fold":
                        ps.folded_to_cbet += 1
                        self.pool_folded_cbet += 1

        if is_vpip:
            ps.vpip_hands += 1
            self.pool_vpip_hands += 1
        if is_pfr:
            ps.pfr_hands += 1
            self.pool_pfr_hands += 1
        if is_3bet:
            ps.three_bet_hands += 1

    def get_shrunk_stats(self, player_id: str) -> tuple[float, float, float, float]:
        if player_id not in self.stats:
            return self.pool_vpip, self.pool_pfr, self.pool_af, self.pool_fold_to_cbet

        ps = self.stats[player_id]
        n = ps.hands
        k = self.shrinkage_k

        w_ind = n / (n + k)
        w_pool = k / (n + k)

        shrunk_vpip = w_ind * ps.observed_vpip + w_pool * self.pool_vpip
        shrunk_pfr = w_ind * ps.observed_pfr + w_pool * self.pool_pfr
        shrunk_af = w_ind * ps.observed_af + w_pool * self.pool_af
        shrunk_fold_cbet = w_ind * ps.observed_fold_to_cbet + w_pool * self.pool_fold_to_cbet

        return shrunk_vpip, shrunk_pfr, shrunk_af, shrunk_fold_cbet

    def get_exploit_offsets(self, player_id: str) -> dict[str, float]:
        if not player_id or player_id not in self.stats:
            return self._get_pool_macro_offsets()

        ps = self.stats[player_id]
        if ps.hands < self.min_sample_gate:
            return self._get_pool_macro_offsets()

        vpip, pfr, af, _ = self.get_shrunk_stats(player_id)

        if vpip < 0.18:
            return {"open_offset": -0.03, "cbet_offset": -0.04, "call_offset": 0.04}
        elif vpip >= 0.35 and pfr < 0.16:
            return {"open_offset": 0.02, "cbet_offset": 0.04, "call_offset": -0.02}
        elif vpip >= 0.35 and af >= 2.2:
            return {"open_offset": 0.02, "cbet_offset": 0.03, "call_offset": -0.03}
        elif 0.18 <= vpip <= 0.28 and 0.14 <= pfr <= 0.24:
            return {"open_offset": 0.0, "cbet_offset": 0.0, "call_offset": 0.0}

        return self._get_pool_macro_offsets()

    def _get_pool_macro_offsets(self) -> dict[str, float]:
        if self.pool_total_hands < 60:
            return {"open_offset": 0.0, "cbet_offset": 0.0, "call_offset": 0.0}

        p_vpip = self.pool_vpip
        if p_vpip < 0.20:
            return {"open_offset": -0.02, "cbet_offset": -0.02, "call_offset": 0.02}
        elif p_vpip > 0.32:
            return {"open_offset": 0.02, "cbet_offset": 0.02, "call_offset": -0.02}

        return {"open_offset": 0.0, "cbet_offset": 0.0, "call_offset": 0.0}