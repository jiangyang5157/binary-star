# Sniper signal / gate analysis — `data/prod/sniper.log`

- daemon runs in log: **6**
- pulses: {'XAUTUSDT': 3160, 'BTCUSDT': 3160}
- logged WAKEs: **22**, sessions: 19
- effective gate config: `{"XAUTUSDT": {"directional_sanity": true, "chaos_survival": true, "min_active_non_trend": 3, "min_active_trend": 1}, "BTCUSDT": {"directional_sanity": true, "chaos_survival": true, "min_active_non_trend": 3, "min_active_trend": 1}}`
- base trigger thresholds: {'XAUTUSDT': 0.34, 'BTCUSDT': 0.36}
- replay validation: confluence 22/22, direction 22/22, fresh-set 22/22

## XAUTUSDT

- pulses: 3160  regimes: {'squeeze': 682, 'non_squeeze': 2478}
- fresh-signal count per pulse: {0: 2110, 1: 739, 2: 263, 3: 44, 4: 4}
- pulses meeting confluence threshold: **665** (emergency-bypass: 207, cooldown-blocked: 43)
- logged wakes: 16; k=3 replay reproduces 15 (missed: [{'t': '10:21:42.816', 'dir': 'BULLISH', 'regime': 'squeeze', 'why': 'cooldown'}])

### detector fire-rate / strength

| detector | fire pulses | rate | median strength | p90 strength |
|---|---|---|---|---|
| cvd_momentum | 619 | 19.6% | 0.43 | 1.00 |
| large_trade | 393 | 12.4% | 0.63 | 0.92 |
| cvd_absorption | 201 | 6.4% | 0.14 | 0.50 |
| positioning_extreme | 98 | 3.1% | 0.57 | 0.61 |
| cvd_divergence | 47 | 1.5% | 0.43 | 0.73 |
| squeeze | 47 | 1.5% | 0.42 | 0.51 |
| boundary_test | 6 | 0.2% | 0.38 | 1.00 |
| liquidation_hunt | 1 | 0.0% | 0.21 | 0.21 |
| volatility_surge | 1 | 0.0% | 0.02 | 0.02 |

### gate counterfactual (non-trend regimes; cooldown modelled from logged wakes)

| min_active_non_trend | wakes | wakes/day | blocked | blocked w/ 1 signal | blocked w/ 2 signals | median conf of blocked |
|---|---|---|---|---|---|---|
| 1 | 277 | 22.16 | 0 | 0 | 0 | None |
| 2 | 118 | 9.44 | 290 | 290 | 0 | 0.429 |
| 3 | 16 | 1.28 | 606 | 355 | 251 | 0.435 |

### wakes

| t | run | dir | conf | regime | fresh | mem | active | opinion | trigger_type |
|---|---|---|---|---|---|---|---|---|---|
| 13:31:37.380 | 0 | BULLISH | 0.55 | ranging | 2 | 1 | cvd_momentum, large_trade | BULLISH | TRADED |
| 22:15:34.787 | 0 | BULLISH | 0.68 | squeeze | 3 | 1 | cvd_momentum, cvd_absorption, large_trade | BULLISH | TRADED |
| 22:22:33.466 | 0 | BULLISH | 0.69 | squeeze | 2 | 2 | cvd_momentum, large_trade | BULLISH | TRADED |
| 17:52:57.428 | 1 | BULLISH | 0.84 | ranging | 3 | 1 | cvd_momentum, cvd_divergence, large_trade | BULLISH | TRADED |
| 18:01:02.811 | 1 | BULLISH | 0.72 | ranging | 2 | 2 | cvd_momentum, large_trade | - | ACTIVE_POSITION |
| 18:26:16.961 | 1 | BULLISH | 0.61 | ranging | 2 | 1 | cvd_divergence, large_trade | BULLISH | TRADED |
| 10:47:07.823 | 1 | BULLISH | 0.64 | ranging | 3 | 1 | cvd_momentum, cvd_divergence | NEUTRAL | NEUTRAL |
| 23:05:08.939 | 2 | BULLISH | 0.66 | ranging | 3 | 1 | cvd_momentum, positioning_extreme | BULLISH | TRADED |
| 10:15:27.479 | 2 | BULLISH | 0.63 | squeeze | 3 | 0 | cvd_momentum, large_trade, positioning_extreme | - | FAILED |
| 10:21:42.816 | 2 | BULLISH | 0.54 | squeeze | 1 | 2 | cvd_momentum | BULLISH | TRADED |
| 11:29:05.346 | 2 | BULLISH | 0.53 | squeeze | 2 | 1 | cvd_momentum, large_trade | - | ACTIVE_POSITION |
| 13:37:46.482 | 2 | BEARISH | 0.85 | ranging | 4 | 0 | cvd_momentum, cvd_divergence, large_trade | NEUTRAL | NEUTRAL |
| 13:42:13.574 | 2 | BEARISH | 0.89 | ranging | 3 | 1 | cvd_momentum, large_trade, boundary_test | NEUTRAL | NEUTRAL |
| 13:45:37.453 | 2 | BEARISH | 0.67 | ranging | 4 | 2 | cvd_momentum, large_trade, positioning_extreme | BEARISH | TRADED |
| 08:02:00.594 | 3 | BEARISH | 0.77 | ranging | 4 | 0 | cvd_momentum, cvd_divergence, large_trade | NEUTRAL | NEUTRAL |
| 10:31:13.580 | 3 | BULLISH | 0.71 | ranging | 3 | 0 | cvd_momentum, cvd_divergence, large_trade | BULLISH | TRADED |

### signed forward return by group (% move in signal direction)

| horizon | group | n | mean | median | p25 | p75 | pos-rate |
|---|---|---|---|---|---|---|---|
| 5pulses | gate_blocked_sd1 | 355 | -0.237 | -0.0 | -0.97 | 0.021 | 34% |
| 5pulses | gate_blocked_sd2 | 251 | -0.288 | -0.02 | -0.382 | 0.002 | 26% |
| 5pulses | passed_gate | 16 | -0.448 | -0.04 | -1.614 | 0.005 | 31% |
| 5pulses | single_signal_fire | 355 | -0.237 | -0.0 | -0.97 | 0.021 | 34% |
| 5pulses | stacked3plus_fire | 16 | -0.448 | -0.04 | -1.614 | 0.005 | 31% |
| 15pulses | gate_blocked_sd1 | 353 | -0.209 | -0.014 | -0.28 | 0.038 | 33% |
| 15pulses | gate_blocked_sd2 | 251 | -0.265 | -0.035 | -0.292 | 0.0 | 23% |
| 15pulses | passed_gate | 16 | -0.366 | -0.046 | -0.355 | 0.002 | 31% |
| 15pulses | single_signal_fire | 353 | -0.209 | -0.014 | -0.28 | 0.038 | 33% |
| 15pulses | stacked3plus_fire | 16 | -0.366 | -0.046 | -0.355 | 0.002 | 31% |
| 30pulses | gate_blocked_sd1 | 350 | -0.093 | -0.016 | -0.12 | 0.025 | 34% |
| 30pulses | gate_blocked_sd2 | 247 | -0.151 | -0.034 | -0.143 | 0.009 | 32% |
| 30pulses | passed_gate | 15 | -0.368 | -0.16 | -0.383 | -0.043 | 13% |
| 30pulses | single_signal_fire | 350 | -0.093 | -0.016 | -0.12 | 0.025 | 34% |
| 30pulses | stacked3plus_fire | 15 | -0.368 | -0.16 | -0.383 | -0.043 | 13% |
| 60pulses | gate_blocked_sd1 | 339 | -0.146 | -0.014 | -0.196 | 0.046 | 43% |
| 60pulses | gate_blocked_sd2 | 216 | -0.219 | -0.023 | -0.301 | 0.027 | 37% |
| 60pulses | passed_gate | 12 | -0.464 | -0.142 | -1.765 | -0.034 | 17% |
| 60pulses | single_signal_fire | 339 | -0.146 | -0.014 | -0.196 | 0.046 | 43% |
| 60pulses | stacked3plus_fire | 12 | -0.464 | -0.142 | -1.765 | -0.034 | 17% |

### 1h ATR-normalised excursions (engine-fire candidates)

| group | n | MFE med (ATR) | MAE med (ATR) | terminal med (ATR) | ran +1ATR first | stopped -1ATR first | chop |
|---|---|---|---|---|---|---|---|
| all_candidates | 622 | +0.13 | -0.51 | -0.10 | 15% | 37% | 48% |
| blocked_sd1_BEAR | 208 | +0.18 | -0.31 | -0.00 | 18% | 22% | 60% |
| blocked_sd1_BULL | 147 | +0.16 | -1.18 | -0.18 | 19% | 52% | 29% |
| blocked_sd2_BEAR | 94 | +0.09 | -0.36 | -0.10 | 5% | 26% | 69% |
| blocked_sd2_BULL | 157 | +0.11 | -0.94 | -0.14 | 14% | 50% | 36% |
| gate_blocked_sd1 | 355 | +0.17 | -0.49 | -0.06 | 19% | 34% | 47% |
| gate_blocked_sd2 | 251 | +0.09 | -0.51 | -0.12 | 11% | 41% | 49% |
| pass_gate | 16 | +0.06 | -1.47 | -0.29 | 6% | 56% | 38% |
| pass_gate_BEAR | 4 | +0.17 | -4.54 | -2.21 | 0% | 75% | 25% |
| pass_gate_BULL | 12 | +0.06 | -1.05 | -0.18 | 8% | 50% | 42% |

## BTCUSDT

- pulses: 3160  regimes: {'squeeze': 762, 'non_squeeze': 2398}
- fresh-signal count per pulse: {0: 2345, 1: 413, 2: 351, 3: 49, 4: 2}
- pulses meeting confluence threshold: **309** (emergency-bypass: 61, cooldown-blocked: 27)
- logged wakes: 6; k=3 replay reproduces 2 (missed: [{'t': '00:31:40.033', 'dir': 'BEARISH', 'regime': 'trending', 'why': 'gate'}, {'t': '00:49:48.233', 'dir': 'BEARISH', 'regime': 'trending', 'why': 'cooldown'}, {'t': '01:43:25.519', 'dir': 'BEARISH', 'regime': 'trending', 'why': 'gate'}, {'t': '11:13:48.865', 'dir': 'BEARISH', 'regime': 'trending', 'why': 'gate'}])

### detector fire-rate / strength

| detector | fire pulses | rate | median strength | p90 strength |
|---|---|---|---|---|
| cvd_momentum | 487 | 15.4% | 0.36 | 0.73 |
| cvd_absorption | 464 | 14.7% | 0.27 | 0.62 |
| large_trade | 214 | 6.8% | 0.59 | 0.74 |
| squeeze | 46 | 1.5% | 0.24 | 0.31 |
| cvd_divergence | 39 | 1.2% | 0.45 | 0.79 |
| liquidation_hunt | 15 | 0.5% | 0.29 | 0.81 |
| boundary_test | 5 | 0.2% | 0.56 | 0.78 |

### gate counterfactual (non-trend regimes; cooldown modelled from logged wakes)

| min_active_non_trend | wakes | wakes/day | blocked | blocked w/ 1 signal | blocked w/ 2 signals | median conf of blocked |
|---|---|---|---|---|---|---|
| 1 | 110 | 8.8 | 0 | 0 | 0 | None |
| 2 | 37 | 2.96 | 151 | 151 | 0 | 0.399 |
| 3 | 2 | 0.16 | 280 | 180 | 100 | 0.411 |

### wakes

| t | run | dir | conf | regime | fresh | mem | active | opinion | trigger_type |
|---|---|---|---|---|---|---|---|---|---|
| 15:15:57.207 | 2 | BULLISH | 0.60 | ranging | 4 | 0 | cvd_momentum, cvd_divergence, cvd_absorption, large_trade | NEUTRAL | NEUTRAL |
| 18:46:53.172 | 2 | BEARISH | 0.71 | ranging | 2 | 1 | cvd_momentum, cvd_divergence | NEUTRAL | NEUTRAL |
| 00:31:40.033 | 2 | BEARISH | 0.69 | trending | 2 | 0 | cvd_momentum, large_trade | NEUTRAL | NEUTRAL |
| 00:49:48.233 | 2 | BEARISH | 0.37 | trending | 1 | 3 | cvd_momentum | NEUTRAL | NEUTRAL |
| 01:43:25.519 | 2 | BEARISH | 0.50 | trending | 1 | 0 | boundary_test | NEUTRAL | NEUTRAL |
| 11:13:48.865 | 2 | BEARISH | 0.41 | trending | 1 | 2 | cvd_momentum | NEUTRAL | NEUTRAL |

### signed forward return by group (% move in signal direction)

| horizon | group | n | mean | median | p25 | p75 | pos-rate |
|---|---|---|---|---|---|---|---|
| 5pulses | gate_blocked_sd1 | 180 | -0.186 | -0.023 | -0.509 | 0.041 | 41% |
| 5pulses | gate_blocked_sd2 | 100 | -0.142 | -0.006 | -0.098 | 0.054 | 46% |
| 5pulses | passed_gate | 2 | -0.358 | -0.358 | -2.023 | -2.023 | 50% |
| 5pulses | single_signal_fire | 180 | -0.186 | -0.023 | -0.509 | 0.041 | 41% |
| 5pulses | stacked3plus_fire | 2 | -0.358 | -0.358 | -2.023 | -2.023 | 50% |
| 15pulses | gate_blocked_sd1 | 179 | -0.138 | -0.033 | -0.274 | 0.095 | 44% |
| 15pulses | gate_blocked_sd2 | 100 | -0.144 | -0.0 | -0.082 | 0.054 | 50% |
| 15pulses | passed_gate | 2 | -0.387 | -0.387 | -2.087 | -2.087 | 50% |
| 15pulses | single_signal_fire | 179 | -0.138 | -0.033 | -0.274 | 0.095 | 44% |
| 15pulses | stacked3plus_fire | 2 | -0.387 | -0.387 | -2.087 | -2.087 | 50% |
| 30pulses | gate_blocked_sd1 | 179 | -0.034 | -0.004 | -0.098 | 0.111 | 49% |
| 30pulses | gate_blocked_sd2 | 97 | -0.055 | 0.026 | -0.093 | 0.104 | 56% |
| 30pulses | passed_gate | 2 | 0.203 | 0.203 | 0.089 | 0.089 | 100% |
| 30pulses | single_signal_fire | 179 | -0.034 | -0.004 | -0.098 | 0.111 | 49% |
| 30pulses | stacked3plus_fire | 2 | 0.203 | 0.203 | 0.089 | 0.089 | 100% |
| 60pulses | gate_blocked_sd1 | 161 | -0.037 | -0.022 | -0.178 | 0.277 | 49% |
| 60pulses | gate_blocked_sd2 | 89 | -0.212 | -0.067 | -0.227 | 0.029 | 30% |
| 60pulses | passed_gate | 2 | 0.144 | 0.144 | 0.047 | 0.047 | 100% |
| 60pulses | single_signal_fire | 161 | -0.037 | -0.022 | -0.178 | 0.277 | 49% |
| 60pulses | stacked3plus_fire | 2 | 0.144 | 0.144 | 0.047 | 0.047 | 100% |

### 1h ATR-normalised excursions (engine-fire candidates)

| group | n | MFE med (ATR) | MAE med (ATR) | terminal med (ATR) | ran +1ATR first | stopped -1ATR first | chop |
|---|---|---|---|---|---|---|---|
| all_candidates | 281 | +0.28 | -0.33 | +0.02 | 18% | 30% | 52% |
| blocked_sd1_BEAR | 110 | +0.36 | -0.35 | +0.03 | 19% | 33% | 48% |
| blocked_sd1_BULL | 69 | +0.23 | -0.37 | -0.08 | 19% | 33% | 48% |
| blocked_sd2_BEAR | 54 | +0.40 | -0.26 | -0.02 | 11% | 30% | 59% |
| blocked_sd2_BULL | 46 | +0.25 | -0.24 | +0.08 | 24% | 15% | 61% |
| gate_blocked_sd1 | 179 | +0.27 | -0.36 | -0.01 | 19% | 33% | 48% |
| gate_blocked_sd2 | 100 | +0.32 | -0.25 | +0.05 | 17% | 23% | 60% |
| pass_gate | 2 | +1.23 | -1.87 | +0.34 | 50% | 50% | 0% |
| pass_gate_BEAR | 1 | +2.32 | -0.39 | +0.55 | 100% | 0% | 0% |
| pass_gate_BULL | 1 | +0.14 | -3.36 | +0.14 | 0% | 100% | 0% |
