"""GTA 6 Trophy Rarity Forecast v2 — Independent Candidate.

Logit-space forecast modelling earned counts and tracked players separately.
Deterministic, Python 3.13 stdlib only, no network, no model calls.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z_SCORES = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# Launch epoch for adoption curve reference
EPOCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)

# Trophy classification based on points (coarse prior)
TIER_SPEED = {
    "platinum": 0.10,
    "gold": 0.30,
    "silver": 0.55,
    "bronze": 0.75,
}


def clamp_pct(x: float) -> float:
    return max(0.01, min(99.99, x))


def logit(pct: float) -> float:
    p = clamp_pct(pct)
    return math.log(p / (100.0 - p))


def inv_logit(lg: float) -> float:
    if lg >= 0:
        return 100.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return 100.0 * e / (1.0 + e)


def round4(x: float):
    """Round to 4 decimal places, half-up."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    val = whole / 10000.0
    return int(val) if float(val).is_integer() else val


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def classify_trophy(trophy: dict) -> tuple[float, str]:
    """Return (speed_prior, class_name) from trophy metadata."""
    name = trophy.get("name", "")
    desc = (trophy.get("description") or "").lower()
    tier = trophy.get("tier", "bronze")
    points = trophy.get("points", 15)

    # Base from tier
    speed = TIER_SPEED.get(tier, 0.6)

    # Story completion trophies (early chapters = fast)
    if "complete chapter 1" in desc:
        return 0.95, "story_early"
    if "complete chapter 2" in desc:
        return 0.85, "story_early"
    if "complete chapter 3" in desc:
        return 0.75, "story_mid"
    if "complete chapter 4" in desc:
        return 0.65, "story_mid"
    if "complete chapter 5" in desc:
        return 0.55, "story_late"

    # Final mission strands
    if "final mission for" in desc:
        return 0.70, "story_mid"

    # Quick one-off activities
    quick_keywords = [
        "gone fishing", "arcade game", "cocktail", "bowling",
        "try each type", "fishing challenge", "photo mode",
        "dance", "karaoke", "darts"
    ]
    if any(kw in desc for kw in quick_keywords):
        return 0.90, "quick_activity"

    # Grind / collectibles (slow, continues for days)
    grind_keywords = [
        "250 stunts", "100 vehicles", "50 challenges", "100 locations",
        "card sets", "20 different races", "gold medal in all",
        "every location", "8 mission strands", "meditate at every",
        "explore all of leonida", "rob 5 bank vaults", "register 10 vehicles",
        "collect all", "find all", "complete all"
    ]
    if any(kw in desc for kw in grind_keywords):
        return 0.20, "grind_collectible"

    # Money / economy trophies
    if "laundering" in desc or "spend $100,000" in desc:
        return 0.35, "economy"
    if "purchase all garage" in desc:
        return 0.30, "economy"

    # 100% completion / platinum
    if "100% completion" in desc or tier == "platinum":
        return 0.10, "completionist"

    # Online / missable (harder to earn)
    if "online" in desc or "multiplayer" in desc or "co-op" in desc:
        return 0.25, "online"

    # Secret trophies — unknown, assume mid-slow
    if trophy.get("secret", False):
        return 0.40, "secret"

    # Fallback by points (higher points = slower generally)
    if points >= 90:
        return 0.30, "gold_tier"
    if points >= 30:
        return 0.50, "silver_tier"
    return speed, "default"


def tracked_growth_factor(case: dict) -> tuple[float, float]:
    """Return (growth_factor, horizon_days) for players_tracked."""
    reads = case["history"]
    last = reads[-1]
    n_last = last["players_tracked"]
    horizon_minutes = case["horizon_minutes"]
    horizon_days = horizon_minutes / 1440.0

    # Observed log-linear trend from history
    g_trend = 1.0
    if len(reads) >= 2:
        n_first = reads[0]["players_tracked"]
        t_first = parse_time(reads[0]["slot"])
        t_last = parse_time(reads[-1]["slot"])
        span_days = max((t_last - t_first).total_seconds(), 0.0) / 86400.0
        if span_days > 0 and n_first > 0 and n_last > n_first:
            rate_per_day = math.log(n_last / n_first) / span_days
            g_trend = math.exp(rate_per_day * horizon_days)

    # Adoption curve prior: launch-day surge then power-law decay
    at = parse_time(case["at"])
    target = parse_time(case["target"])
    t_at = max((at - EPOCH).total_seconds() / 3600.0, 0.5)  # hours since launch
    t_target = max((target - EPOCH).total_seconds() / 3600.0, 0.5)

    # Power-law: growth ~ t^0.4 from checkpoint to target
    g_adoption = (t_target / t_at) ** 0.4 if t_at > 0 else 1.0

    # Refresh batch effect (Exophase refreshes ~5x in short windows)
    if horizon_minutes < 360:  # < 6 hours
        g_refresh = 5.0
    else:
        g_refresh = 1.0 + 2.0 * math.log10(max(horizon_minutes / 60.0, 1.0))

    # Combine: max of trend, adoption, refresh, capped at 10x
    g = max(g_trend, g_adoption, g_refresh)
    return min(g, 10.0), horizon_days


def earned_catchup_factor(speed: float, horizon_days: float, g_n: float) -> float:
    """Fraction of new players who earn the trophy by target.
    Fast trophies catch up more; slow trophies less."""
    # Base catch-up scales with speed and log horizon
    base = speed * math.log1p(horizon_days * 2.0) / math.log1p(horizon_days * 2.0 + 1.0)
    # Dilution from denominator growth: new players need time to earn
    dilution = 1.0 - 0.3 * (1.0 - speed) * math.log1p(g_n - 1.0) / math.log1p(9.0)
    return max(0.0, min(1.0, base * dilution))


def logit_spread(horizon_days: float, g_n: float, speed: float, rate: float) -> float:
    """Total uncertainty in logit space. Widens with horizon, refresh risk, adoption uncertainty."""
    # Base aleatoric uncertainty
    base_sigma = 0.50

    # Random walk component ~ sqrt(days)
    rw_sigma = 0.70 * math.sqrt(max(horizon_days, 0.0))

    # Refresh batch uncertainty (large for short horizons near refresh times)
    refresh_sigma = 1.1 if horizon_days < 0.5 else 0.6

    # Adoption curve uncertainty (how many new players arrive)
    adoption_sigma = 0.4 * math.log1p(g_n - 1.0) / math.log1p(9.0)

    # Speed-dependent: slow trophies have more relative uncertainty at low rates
    speed_sigma = 0.3 * (1.0 - speed) if rate < 5.0 else 0.15 * (1.0 - speed)

    # Combine in quadrature
    total = math.sqrt(
        base_sigma**2 +
        rw_sigma**2 +
        refresh_sigma**2 +
        adoption_sigma**2 +
        speed_sigma**2
    )
    return min(total, 2.5)  # Cap


def forecast_case(case: dict, case_name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{case_name}: expected levels {LEVELS}, got {case['levels']}")
    if not case["history"]:
        raise ValueError(f"{case_name}: empty history")

    last = case["history"][-1]
    n_last = last["players_tracked"]
    rates = last["rates"]

    g_n, horizon_days = tracked_growth_factor(case)
    n_target = n_last * g_n

    results = []
    for i, trophy in enumerate(case["trophies"]):
        rate = rates[i] if i < len(rates) and rates[i] is not None else 0.0
        speed, t_class = classify_trophy(trophy)

        # Handle near-100% artefact trophy (id where all tracked have it)
        if rate >= 99.5:
            # Count model: old players keep it, new players earn at catch-up rate
            catchup = earned_catchup_factor(speed, horizon_days, g_n)
            earned_old = n_last * 1.0
            earned_new = (n_target - n_last) * catchup
            median_pct = (earned_old + earned_new) / n_target * 100.0
        else:
            # Logit-space median shift
            # Dilution from denominator growth
            dilution = -math.log(g_n)
            # Catch-up earning (partially offsets dilution)
            catchup = earned_catchup_factor(speed, horizon_days, g_n)
            catchup_bonus = 1.5 * speed * math.log1p(horizon_days) * catchup
            # Net shift
            shift = dilution * (1.0 - 0.3 * speed) + catchup_bonus
            median_pct = inv_logit(logit(rate) + shift)

        median_pct = clamp_pct(median_pct)
        lg_med = logit(median_pct)
        sigma = logit_spread(horizon_days, g_n, speed, rate)

        # Generate quantiles in logit space, then inverse
        qs = []
        prev = 0.0
        for z in Z_SCORES:
            q = inv_logit(lg_med + z * sigma)
            q = round4(max(0.0, min(100.0, q)))
            q = max(q, prev)  # enforce non-decreasing after rounding
            qs.append(q)
            prev = q

        results.append({"id": trophy["id"], "q": qs})

    return {"trophies": results}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()