"""Symbol search – typeahead over the Dhan instrument master."""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Query

from app.engines.dhan_client import INDEX_MAP

logger = logging.getLogger(__name__)
router = APIRouter()

_INDEX: List[Dict] = []
_LOADED = False


def _index_label_to_our_format(trading_symbol: str) -> Optional[str]:
    """Map Dhan's INDEX trading_symbol (e.g. 'NIFTY', 'BANKNIFTY', 'NIFTY 500') to our
    'NSE:<KEY>-INDEX' format, but only for indices our DhanClient can resolve."""
    cleaned = trading_symbol.replace(" ", "").upper()
    aliases = {
        "NIFTY": "NIFTY50",
    }
    key = aliases.get(cleaned, cleaned)
    if key in INDEX_MAP:
        return f"NSE:{key}-INDEX"
    return None


def _load_index():
    global _LOADED
    if _LOADED:
        return
    path = Path(__file__).resolve().parents[4] / "data" / "dhan_scrip_master.csv"
    if not path.exists():
        logger.warning(f"Symbol master not found at {path}")
        _LOADED = True
        return

    seen = set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exch = row.get("SEM_EXM_EXCH_ID")
            instrument = row.get("SEM_INSTRUMENT_NAME") or ""
            ts = (row.get("SEM_TRADING_SYMBOL") or "").strip()
            name = (row.get("SEM_CUSTOM_SYMBOL") or row.get("SM_SYMBOL_NAME") or ts).strip()
            if not ts:
                continue

            symbol = None
            row_type = None
            if exch == "NSE" and instrument == "EQUITY":
                symbol = f"NSE:{ts}-EQ"
                row_type = "EQUITY"
            elif exch == "BSE" and instrument == "EQUITY":
                symbol = f"BSE:{ts}-EQ"
                row_type = "EQUITY"
            elif exch == "NSE" and instrument == "INDEX":
                mapped = _index_label_to_our_format(ts)
                if not mapped:
                    continue
                symbol = mapped
                row_type = "INDEX"
            elif exch == "MCX" and instrument == "FUTCOM":
                symbol = f"MCX:{ts}"
                row_type = "FUTCOM"
            else:
                continue

            if symbol in seen:
                continue
            seen.add(symbol)
            _INDEX.append({
                "symbol": symbol,
                "name": name,
                "type": row_type,
                "exchange": exch,
            })
    logger.info(f"Symbol search index loaded: {len(_INDEX)} entries")
    _LOADED = True


def _score(row: Dict, q_upper: str) -> int:
    """Higher = better match. Tiebreakers: prefer INDEX, NSE, shorter tickers."""
    if not q_upper:
        # Empty query → keep stable, but float indices and NSE up.
        base = 0
    else:
        s = row["symbol"].upper()
        n = (row.get("name") or "").upper()
        bare = s.split(":", 1)[1].split("-", 1)[0] if ":" in s else s
        if bare == q_upper: base = 1000
        elif bare.startswith(q_upper): base = 700
        elif n.startswith(q_upper): base = 500
        elif q_upper in bare: base = 300
        elif q_upper in n: base = 200
        else: base = 0
        # Tiebreaker: shorter bare ticker beats longer (less padding around the match)
        base -= max(0, len(bare) - len(q_upper)) * 2

    # Type bonuses
    if row.get("type") == "INDEX": base += 60
    elif row.get("type") == "EQUITY": base += 20
    # Exchange bonuses (NSE preferred for Indian universe)
    if row.get("exchange") == "NSE": base += 12
    return base


@router.get("/search")
async def search_symbols(
    q: str = Query(default="", description="Free-text query — ticker or name fragment"),
    limit: int = Query(default=20, ge=1, le=100),
    exchange: Optional[str] = Query(default=None, description="NSE, BSE, MCX"),
    type: Optional[str] = Query(default=None, description="EQUITY, INDEX, FUTCOM"),
):
    _load_index()
    q_upper = q.strip().upper()

    candidates: List[Dict] = []
    for row in _INDEX:
        if exchange and row["exchange"] != exchange.upper():
            continue
        if type and row["type"] != type.upper():
            continue
        s_upper = row["symbol"].upper()
        n_upper = (row.get("name") or "").upper()
        if q_upper and q_upper not in s_upper and q_upper not in n_upper:
            continue
        candidates.append(row)

    candidates.sort(key=lambda r: _score(r, q_upper), reverse=True)
    return {"count": len(candidates[:limit]), "results": candidates[:limit], "total_indexed": len(_INDEX)}
