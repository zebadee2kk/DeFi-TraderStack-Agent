"""Parameter fitting for walk-forward evaluation.

`WalkForwardEvaluator` accepts an optional `fit` hook: a callable that receives
only the train-window candles and returns a (possibly parameter-tuned)
`BaselineBacktester` to run on the held-out test window. Left unset, walk-forward
behaves exactly as before (the same backtester on every fold, no fitting).

`grid_search_momentum_lookback` builds one such hook: it grid-searches the
ensemble's momentum-strategy lookback over a small candidate space, scoring each
candidate strictly on the train window, and returns the best-scoring backtester
for use on test. Because the hook only ever receives the train slice, this
composes directly with `research.leakage.assert_no_lookahead` to prove fitting
never touches test-window data.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle

ScoreFn = Callable[[BacktestMetrics], float]


def _default_score(metrics: BacktestMetrics) -> float:
    return metrics.sharpe


def grid_search_momentum_lookback(
    base_backtester: BaselineBacktester,
    candidates: Iterable[int] = (6, 12, 18, 24, 30),
    *,
    score: ScoreFn = _default_score,
) -> Callable[[tuple[Candle, ...]], BaselineBacktester]:
    """Build a `WalkForwardEvaluator.fit` hook that tunes the momentum lookback.

    For each candidate lookback, builds a backtester with that lookback swapped
    into the ensemble's momentum strategy, backtests it on the train window
    only, and scores it with `score` (default: Sharpe ratio). Returns a fit hook
    that always picks the best-scoring candidate; falls back to
    `base_backtester` unchanged if every candidate fails (e.g. too little train
    history) or none is provided.
    """

    def fit(train_candles: tuple[Candle, ...]) -> BaselineBacktester:
        best: BaselineBacktester | None = None
        best_score = float("-inf")
        for lookback in candidates:
            momentum_strategy = replace(base_backtester.ensemble.momentum_strategy, lookback=lookback)
            ensemble = replace(base_backtester.ensemble, momentum_strategy=momentum_strategy)
            candidate = replace(base_backtester, ensemble=ensemble)
            try:
                metrics = candidate.run(train_candles)
            except ValueError:
                continue
            candidate_score = score(metrics)
            if candidate_score > best_score:
                best_score = candidate_score
                best = candidate
        return best if best is not None else base_backtester

    return fit
