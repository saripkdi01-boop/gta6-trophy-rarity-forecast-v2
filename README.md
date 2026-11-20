# GTA 6 Trophy Rarity Forecast v2

[![MAKE.FUN](https://img.shields.io/badge/MAKE.FUN-gta6--trophy--rarity--forecast--01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![MAKE.FUN rank](https://img.shields.io/badge/MAKE.FUN-rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![MAKE.FUN reward](https://img.shields.io/badge/MAKE.FUN-reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Independent v2 candidate for **make.fun** bounty *gta6-trophy-rarity-forecast-01*.

Forecasts each trophy's Exophase earn rate at the case's target as five quantiles (5/25/50/75/95%) in percent.

## Approach

- **Logit-space modelling**: All interpolation and uncertainty in log-odds space, inverse-transformed to percent.
- **Separate processes**: Models `players_tracked` growth (denominator) and trophy `earned` counts (numerator) independently.
- **Tracked growth**: Combines observed log-linear trend, launch adoption curve (power-law ~t^0.4), and Exophase refresh batch prior (~5× on short horizons), capped at 10×.
- **Earned catch-up**: Fast trophies (story early, quick activities) catch up strongly on new players; grind/collectible/online trophies catch up weakly. Near-100% artefacts handled via count model.
- **Spread**: Quadrature sum of base aleatoric, random-walk (~√days), refresh batch risk, adoption uncertainty, and speed-dependent terms. Widens with horizon.
- **Trophy classification**: Tier + description keywords → speed prior (0.10–0.95) and class label. No per-trophy history fitting (history is flat in practice).
- **Deterministic**: Pure Python 3.13 stdlib, no network, no external deps. Byte-identical outputs across runs.

## Run

```bash
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads `*.in` from `$MAKEFUN_INPUT_DIR` (default `/input`), writes `*.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`).

## License

MIT — see [LICENSE](LICENSE).