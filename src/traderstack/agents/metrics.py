"""Prometheus counters for the constrained meta-agent (Epic 6).

Follows the pattern in `src/traderstack/health.py`: module-level counters from
`prometheus-client`, scraped by the exporter the CLI already starts.
"""

from prometheus_client import Counter, Gauge

meta_agent_reviews_total = Counter(
    "traderstack_meta_agent_reviews_total",
    "Meta-agent reviews by mode and outcome",
    ("mode", "outcome"),
)
meta_agent_tokens_total = Counter(
    "traderstack_meta_agent_tokens_total",
    "Meta-agent tokens consumed",
    ("kind",),
)
meta_agent_cost_usd_total = Counter(
    "traderstack_meta_agent_cost_usd_total",
    "Estimated meta-agent spend in USD",
)
meta_agent_suppressed_orders_total = Counter(
    "traderstack_meta_agent_suppressed_orders_total",
    "Paper orders suppressed by the meta-agent in veto mode",
    ("reason",),
)
meta_agent_daily_calls = Gauge(
    "traderstack_meta_agent_daily_calls",
    "Meta-agent calls made so far in the current UTC day",
)
meta_agent_daily_tokens = Gauge(
    "traderstack_meta_agent_daily_tokens",
    "Meta-agent tokens consumed so far in the current UTC day",
)
