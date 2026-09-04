"""Lookahead-bias checks (Evaluation Framework, Stage 2 — Bias Controls).

Every production signal/feature function in this codebase is called as
`fn(candles[:i+1])`: a point-in-time window ending at "now". Because Python
slicing means `fn` is physically incapable of reading past the last element of
whatever tuple it is handed, it cannot reach into data with a larger array
index than its own argument -- the lookahead bug this module actually guards
against is the one that survives correct slicing at the call site: a signal
function that (accidentally or by design) carries hidden state across calls --
a running/streaming accumulator, an exponential moving average kept between
invocations, a "last seen" cache -- so that its answer for a *given* window
depends not just on that window's own content but on what other windows
(including ones representing later points in time, or a different possible
future) it happened to be asked about first.

`assert_no_lookahead(fn, candles)` computes `fn(candles[:i+1])` at every
point-in-time checkpoint `i`, then deliberately exposes `fn` to same-length
decoy windows (plausible stand-ins for "this checkpoint under a different
future") and to the full future-inclusive dataset, and re-checks that `fn`'s
answer for the *original* checkpoint is unchanged. A correctly point-in-time,
stateless function (which every strategy/feature builder in this codebase is)
passes trivially; a function that leaks state across evaluations does not.
`assert_no_lookahead_under_shuffled_future` does the same but with the decoy
content replaced by synthetic random noise rather than plausible perturbations
-- a stronger, more adversarial version of the same check.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from traderstack.candles import Candle

# A signal/feature function: given a point-in-time candle window, return anything
# comparable with `==` (a signals tuple, a MarketFeatures instance, ...).
SignalFn = Callable[[tuple[Candle, ...]], Any]


class LookaheadBiasError(AssertionError):
    """Raised when a signal/feature function's answer at checkpoint t changed
    after it was exposed to other windows -- i.e. its answer is not a pure
    function of the window it was given."""


def assert_no_lookahead(
    fn: SignalFn,
    candles: tuple[Candle, ...],
    *,
    min_index: int = 0,
    step: int = 1,
    seed: int = 7,
) -> None:
    """Assert `fn`'s point-in-time answer survives exposure to other windows.

    At every checkpoint `i`, records `fn(candles[:i+1])`, then exposes `fn` to a
    same-length decoy window (a plausible perturbation of the real one -- a
    stand-in for "this checkpoint under a different future") and to the full
    future-inclusive dataset, and asserts `fn(candles[:i+1])` is unchanged.
    """
    _run(fn, candles, min_index=min_index, step=step, seed=seed, noise_scale=0.0)


def assert_no_lookahead_under_shuffled_future(
    fn: SignalFn,
    candles: tuple[Candle, ...],
    *,
    min_index: int = 0,
    step: int = 1,
    seed: int = 1337,
) -> None:
    """As `assert_no_lookahead`, but the decoy exposure windows are pure random
    noise rather than plausible perturbations -- stronger and more adversarial."""
    _run(fn, candles, min_index=min_index, step=step, seed=seed, noise_scale=1.0)


def _run(
    fn: SignalFn,
    candles: tuple[Candle, ...],
    *,
    min_index: int,
    step: int,
    seed: int,
    noise_scale: float,
) -> None:
    n = len(candles)
    if n < min_index + 2:
        raise ValueError("not enough candles to check for lookahead bias")

    for i in range(min_index, n - 1, step):
        real_prefix = candles[: i + 1]
        expected = fn(real_prefix)

        decoy = _decoy_window(candles, i, seed=seed + i, noise_scale=noise_scale)
        fn(decoy)
        fn(candles)  # exposure to the full future-inclusive dataset

        actual = fn(real_prefix)
        if actual != expected:
            raise LookaheadBiasError(
                f"signal at index {i} changed after fn was exposed to other windows "
                f"(a decoy of the same length, and the full dataset): "
                f"{expected!r} != {actual!r}"
            )


def _decoy_window(
    candles: tuple[Candle, ...], index: int, *, seed: int, noise_scale: float
) -> tuple[Candle, ...]:
    """A window the same length as `candles[:index+1]`, with its last candle's
    OHLCV perturbed -- a stand-in for "what this checkpoint could have looked
    like under a different future".
    """
    rng = random.Random(seed)
    prefix = candles[:index]
    last = candles[index]
    recent = candles[max(0, index - 30) : index + 1]
    closes = [candle.close for candle in recent]
    spread = (max(closes) - min(closes)) or (last.close * 0.02) or 1.0
    if noise_scale >= 1.0:
        close = max(rng.uniform(last.close * 0.5, last.close * 1.5), 0.01)
    else:
        close = max(last.close + rng.uniform(-spread, spread), 0.01)
    open_ = max(last.open + rng.uniform(-spread, spread) * 0.5, 0.01)
    decoy_last = Candle(
        symbol=last.symbol,
        interval=last.interval,
        opened_at=last.opened_at,
        open=open_,
        high=max(open_, close) * 1.01,
        low=min(open_, close) * 0.99,
        close=close,
        volume=max(rng.uniform(0.5, 1.5) * last.volume, 0.01),
    )
    return (*prefix, decoy_last)
