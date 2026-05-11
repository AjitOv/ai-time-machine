"""Live tick feed — proxies Dhan WebSocket to the browser.

Frontend connects to:
    ws://host/api/v1/feed/ws?symbol=NSE:NIFTY50-INDEX

and receives JSON messages:
    {"symbol":"NSE:NIFTY50-INDEX","ltp":24017.65,"ltt":"2026-04-29 09:31:17"}
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engines.dhan_feed import get_feed_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def feed_ws(websocket: WebSocket):
    await websocket.accept()
    symbol = websocket.query_params.get("symbol")
    if not symbol:
        await websocket.send_json({"error": "missing symbol query param"})
        await websocket.close()
        return

    mgr = get_feed_manager()
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    ok = await mgr.subscribe(symbol, queue)
    if not ok:
        await websocket.send_json({"error": f"unknown or unresolvable symbol: {symbol}"})
        await websocket.close()
        return

    await websocket.send_json({"event": "subscribed", "symbol": symbol})
    logger.info(f"feed/ws client subscribed to {symbol}")

    async def pump_ticks():
        while True:
            tick = await queue.get()
            await websocket.send_json(tick)

    pump_task = asyncio.create_task(pump_ticks())
    try:
        # The frontend may send messages (e.g. switch symbol); we accept that here.
        while True:
            msg = await websocket.receive_text()
            # Only one supported message: {"action":"switch","symbol":"..."}
            try:
                import json
                data = json.loads(msg)
            except Exception:
                continue
            if data.get("action") == "switch":
                new_sym = data.get("symbol")
                if not new_sym or new_sym == symbol:
                    continue
                await mgr.unsubscribe(symbol, queue)
                symbol = new_sym
                ok2 = await mgr.subscribe(symbol, queue)
                if ok2:
                    await websocket.send_json({"event": "subscribed", "symbol": symbol})
                else:
                    await websocket.send_json({"event": "error", "symbol": symbol, "message": "unresolvable"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"feed/ws error: {e}")
    finally:
        pump_task.cancel()
        await mgr.unsubscribe(symbol, queue)
        try:
            await websocket.close()
        except Exception:
            pass
