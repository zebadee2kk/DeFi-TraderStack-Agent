"""Lower-turnover catalog is a fresh frozen set; default K=13 stays untouched."""

from traderstack.research.xs_topk import (
    CATALOGS,
    CONTROL_ID,
    CORE_IDS,
    LOWTURN_CATALOG,
    LOWTURN_CORE_IDS,
    LOWTURN_IDS,
    LOWTURN_LOOKBACKS,
    TOPK_CATALOG,
    TOPK_IDS,
    TOPK_LOOKBACKS,
    resolve_catalog,
)


def test_lowturn_catalog_is_distinct_from_default() -> None:
    assert TOPK_LOOKBACKS == (21, 63, 126)
    assert LOWTURN_LOOKBACKS == (126, 252, 378)
    assert len(TOPK_CATALOG) == 12
    assert len(LOWTURN_CATALOG) == 12
    assert len(CORE_IDS) == 13
    assert len(LOWTURN_CORE_IDS) == 13
    assert set(TOPK_IDS).isdisjoint(set(LOWTURN_IDS))
    assert all(cid.startswith("xs_topk_lt_") for cid in LOWTURN_IDS)
    assert CONTROL_ID in LOWTURN_CORE_IDS
    assert resolve_catalog("default") == TOPK_CATALOG
    assert resolve_catalog("lowturn") == LOWTURN_CATALOG
    assert set(CATALOGS) == {"default", "lowturn"}


def test_resolve_catalog_rejects_unknown() -> None:
    try:
        resolve_catalog("retune_after_pnl")
    except ValueError as exc:
        assert "unknown catalog" in str(exc)
    else:
        raise AssertionError("expected ValueError")
