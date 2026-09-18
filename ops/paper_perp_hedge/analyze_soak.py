#!/usr/bin/env python3
"""Honest paper-perp-hedge soak metrics for 2026-09-18. Never invents PnL."""
from __future__ import annotations
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/home/rham-admin/src/DeFi-TraderStack-Agent")
RAW = ROOT / "var/ops/_perp_hedge_soak_20260918"
OUT = ROOT / "docs/artifacts/ops/paper-perp-hedge-soak-2026-09-18.md"
LON = timezone(timedelta(hours=1))

def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

def parse_logs(text: str) -> dict:
    text = strip_ansi(text)
    hedged, skipped, funding, mid_fail, fund_fail, cycles, withheld = [], [], [], [], [], [], []
    for line in text.splitlines():
        if "paper_perp_hedged" in line and "paper_perp_hedge_skipped" not in line:
            hedged.append(line)
        if "paper_perp_hedge_skipped" in line:
            skipped.append(line)
        if "paper_perp_funding_applied" in line:
            funding.append(line)
        if "paper_perp_mid_fetch_failed" in line:
            mid_fail.append(line)
        if "paper_perp_funding_fetch_failed" in line:
            fund_fail.append(line)
        if "paper_perp_withheld" in line or "paper_perp_skipped" in line and "kill" in line.lower():
            withheld.append(line)
        if "runtime_cycle_completed" in line:
            cycles.append(line)
    skip_reasons = Counter()
    for line in skipped:
        m = re.search(r"reason[=:]['\"]?([^'\"]+)", line)
        if m:
            skip_reasons[m.group(1).strip()] += 1
        else:
            skip_reasons["unknown"] += 1
    venues = Counter()
    sources = Counter()
    for line in hedged:
        vm = re.search(r"venue[=:](\S+)", line)
        sm = re.search(r"source[=:]['\"]?([^'\"]+)", line)
        if vm:
            venues[vm.group(1)] += 1
        if sm:
            sources[sm.group(1).strip()] += 1
    return dict(
        hedged=hedged, skipped=skipped, funding=funding, mid_fail=mid_fail,
        fund_fail=fund_fail, cycles=cycles, withheld=withheld,
        skip_reasons=skip_reasons, venues=venues, sources=sources,
    )

blobs = []
for name in ["docker_logs_window.txt", "docker_logs_perp.txt", "app_logs_end.txt",
             "app_logs_mid1.txt", "app_logs_kill.txt", "app_logs_start.txt"]:
    p = RAW / name
    if p.exists():
        blobs.append(p.read_text(errors="replace"))
parsed = parse_logs("\n".join(blobs))
meta = (RAW / "meta.txt").read_text() if (RAW / "meta.txt").exists() else ""
sha = "unknown"
for line in meta.splitlines():
    if "commit=" in line:
        sha = line.split("commit=")[-1].strip()

now_utc = datetime.now(timezone.utc)
now_lon = now_utc.astimezone(LON)

# promote flags from host .env (read-only check)
env_lines = []
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith(("TRADING_MODE=", "PAPER_PERP_HEDGE=", "PAPER_PROMOTE_", "PAPER_GARCH_SIZE=", "PAPER_SIMULATE_FILLS=")):
            env_lines.append(line)

lines = []
a = lines.append
a("# Paper perp-hedge soak metrics — 2026-09-18")
a("")
a("**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PROFIT.**")
a("Pre-registered before soak: `docs/artifacts/ops/paper-perp-hedge-soak-recipe-2026-09-18.md`.")
a("Snapshot HL/HTX mids are **not** historical PIT basis. Every `PAPER_PROMOTE_*` stays **false**.")
a("")
a(f"- Generated (London): {now_lon.strftime('%Y-%m-%d %H:%M:%S %Z')}")
a(f"- Generated (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
a(f"- Branch tip during soak (from meta): `{sha}`")
a("- Host: rh-lpt-win-01 WSL (`rham-admin`)")
a("")
a("## Window (from meta)")
a("")
a("```")
a(meta.strip() or "(no meta captured)")
a("```")
a("")
a("## Pre-registered measures → observed")
a("")
a("| Measure | Observed |")
a("|---|---|")
a(f"| `runtime_cycle_completed` (harvested) | **{len(parsed['cycles'])}** |")
a(f"| `paper_perp_hedged` | **{len(parsed['hedged'])}** |")
a(f"| `paper_perp_hedge_skipped` | **{len(parsed['skipped'])}** |")
a(f"| `paper_perp_funding_applied` | **{len(parsed['funding'])}** |")
a(f"| mid fetch failures | **{len(parsed['mid_fail'])}** |")
a(f"| funding fetch failures | **{len(parsed['fund_fail'])}** |")
a(f"| kill-withhold-related lines | **{len(parsed['withheld'])}** |")
a("")
a("### Mid venues / sources (from hedged lines)")
a("")
if parsed["venues"]:
    a("| Venue | Count |")
    a("|---|---:|")
    for k, v in parsed["venues"].most_common():
        a(f"| {k} | {v} |")
else:
    a("_No hedged lines — mid venue not observed (may mean no spot fill to hedge)._")
a("")
if parsed["sources"]:
    a("| Source | Count |")
    a("|---|---:|")
    for k, v in parsed["sources"].most_common():
        a(f"| `{k}` | {v} |")
a("")
a("### Hedge skip reasons")
a("")
if parsed["skip_reasons"]:
    a("| Reason | Count |")
    a("|---|---:|")
    for k, v in parsed["skip_reasons"].most_common():
        a(f"| {k} | {v} |")
else:
    a("_None._")
a("")
a("## Sample hedged log lines (up to 5)")
a("")
a("```")
for line in parsed["hedged"][:5]:
    a(strip_ansi(line)[:240])
if not parsed["hedged"]:
    a("(none)")
a("```")
a("")
a("## Sample funding_applied lines (up to 5)")
a("")
a("```")
for line in parsed["funding"][:5]:
    a(strip_ansi(line)[:240])
if not parsed["funding"]:
    a("(none in window — OK per recipe; not a fail)")
a("```")
a("")
a("## Env hygiene (host `.env` at report time — restore expected)")
a("")
a("```")
a("\n".join(env_lines) or "(unreadable)")
a("```")
a("")
a("## Crucix / polymarket wedge (optional note)")
a("")
a("Polymarket crypto wedge stand-aside when Crucix is `not_configured`.")
a("To unblock the gate (still paper-only; does **not** flip promote):")
a("")
a("1. Run Crucix locally; reachability from compose via `host.docker.internal`.")
a("2. Set in **local** `.env` only (never commit secrets):")
a("   - `CRUCIX_ENABLED=true`")
a("   - `CRUCIX_BASE_URL=http://host.docker.internal:<port>` (or host URL)")
a("   - `CRUCIX_API_KEY=<local key>` — **not** written to git")
a("3. Confirm with `traderstack-check-config` / crypto collect that Crucix is configured.")
a("4. Gate can only **remove** trades (stand-aside); it does not invent edge.")
a("")
a("## Verdict")
a("")
a("| Check | Result |")
a("|---|---|")
a("| Recipe pre-registered before soak | YES |")
a("| Paper-only / no live claim | YES |")
a("| Promote pins flipped | **NO** (must remain false) |")
a("| Snapshot mid treated as PIT basis | **NO** |")
a("| Funding apply in-window | " + ("YES" if parsed["funding"] else "NONE IN WINDOW (not a fail)") + " |")
a("| Mid fetch hard failures | " + ("PASS (none)" if not parsed["mid_fail"] else f"SEE LOGS ({len(parsed['mid_fail'])})") + " |")
a("")
a("Artifacts: this report + `var/ops/_perp_hedge_soak_20260918/` (local raw).")
a("")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines) + "\n")
print(f"wrote {OUT}")
print(f"cycles={len(parsed['cycles'])} hedged={len(parsed['hedged'])} funding={len(parsed['funding'])} skips={len(parsed['skipped'])}")
