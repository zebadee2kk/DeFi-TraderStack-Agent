"""Paper-trading acceptance drills (Epic 10).

Three pieces, all offline and deterministic:

* ``market`` -- a seeded synthetic random-walk market (candles + ticks) so an
  acceptance run never touches the network and always reproduces.
* ``faults`` -- composable fault-injection wrappers around every external
  dependency the live loop has (venue feed, reference prices, candle history,
  intelligence, meta-agent, executor, reconcilers, event sinks), each with
  ``arm()`` / ``disarm()`` and a counter of how many times it fired.
* ``soak`` / ``report`` -- the ``traderstack-soak`` acceptance runner and the
  ``traderstack-paper-report`` paper-performance-versus-baselines report.

Nothing in this package is imported by the trading runtime; it exists to prove
the documented fail-closed behaviour, not to participate in it.
"""
