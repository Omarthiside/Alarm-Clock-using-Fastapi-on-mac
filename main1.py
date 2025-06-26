
import asyncio
import datetime
import logging
import traceback
from collections import defaultdict

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
DATABASE_URL = "sqlite:///./alarms.db"  # Persist APScheduler jobs
PING_INTERVAL = 20  # Seconds between heartbeat pings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -------------------------------------------------------------
# FastAPI & APScheduler setup
# -------------------------------------------------------------
app = FastAPI()

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=DATABASE_URL)},
    executors={"default": AsyncIOExecutor()},
    job_defaults={"misfire_grace_time": 30},  # 30‑second grace for missed jobs
    timezone="UTC",
)
scheduler.start()

# Active websockets per client_id
active_connections: defaultdict[str, set[WebSocket]] = defaultdict(set)

# -------------------------------------------------------------
# Utility helpers
# -------------------------------------------------------------

def remove_jobs_for_client(client_id: str) -> None:
    """Remove every scheduled alarm belonging to client_id."""
    for job in scheduler.get_jobs():
        if job.args and job.args[0] == client_id:
            scheduler.remove_job(job.id)


async def heartbeat(ws: WebSocket):
    """Ping the browser regularly so we can detect dead TCP connections."""
    while True:
        await asyncio.sleep(PING_INTERVAL)
        await ws.send_json({"type": "ping"})


async def send_alarm_to_client(client_id: str):
    """Send an alarm to all active websockets of client_id with retries."""
    logging.info("Alarm triggered for %s", client_id)
    conns = list(active_connections.get(client_id, []))
    if not conns:
        logging.warning("No active connection for %s", client_id)
        return

    payload = {"type": "alarm_goes_off"}

    for ws in conns:
        delivered = False
        for attempt in range(3):  # retry ×3 with exponential back‑off
            try:
                await ws.send_json(payload)
                delivered = True
                break
            except Exception as exc:
                logging.warning("Send attempt %s failed for %s: %s", attempt + 1, client_id, exc)
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s waits
        if not delivered:
            logging.error("Failed to deliver alarm to %s after retries", client_id)


# -------------------------------------------------------------
# WebSocket endpoint
# -------------------------------------------------------------

@app.websocket("/alarm/")
async def alarm_endpoint(
    websocket: WebSocket,
    client_id: str = Query(..., description="Unique identifier for this client/user"),
):
    await websocket.accept()
    active_connections[client_id].add(websocket)
    logging.info("%s connected (now %d socket(s))", client_id, len(active_connections[client_id]))

    # Heartbeat coroutine keeps the TCP connection alive and detects failures
    hb_task = asyncio.create_task(heartbeat(websocket))

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # --------------------------------------------------
            #   SET ALARM
            # --------------------------------------------------
            if msg_type == "set_alarm":
                try:
                    alarm_time = datetime.datetime.strptime(data["time"], "%Y-%m-%d %H:%M:%S")
                except (KeyError, ValueError):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Time must be in 'YYYY-MM-DD HH:MM:SS' format",
                    })
                    continue

                job_id = f"{client_id}_{alarm_time.timestamp()}"
                scheduler.add_job(
                    send_alarm_to_client,
                    trigger=DateTrigger(run_date=alarm_time),
                    args=[client_id],
                    id=job_id,
                    replace_existing=True,
                )
                await websocket.send_json({"type": "set_alarm", "message": f"Alarm set for {alarm_time}"})

            # --------------------------------------------------
            #   SNOOZE (fixed 10‑minute snooze)
            # --------------------------------------------------
            elif msg_type == "snooze":
                snooze_until = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
                job_id = f"{client_id}_{snooze_until.timestamp()}"
                scheduler.add_job(
                    send_alarm_to_client,
                    trigger=DateTrigger(run_date=snooze_until),
                    args=[client_id],
                    id=job_id,
                    replace_existing=True,
                )
                await websocket.send_json({"type": "snooze", "message": f"Snoozed until {snooze_until}"})

            # --------------------------------------------------
            #   STOP ALL ALARMS
            # --------------------------------------------------
            elif msg_type == "stop_alarm":
                remove_jobs_for_client(client_id)
                await websocket.send_json({"type": "stop_alarm", "message": "All alarms stopped."})

            # --------------------------------------------------
            #   Heartbeat reply (optional "pong" handling)
            # --------------------------------------------------
            elif msg_type == "pong":
                continue  # Client answered our ping; nothing else to do.

    except WebSocketDisconnect:
        logging.info("%s disconnected", client_id)
    except Exception as exc:
        logging.error("Unexpected error for %s: %s", client_id, exc)
        traceback.print_exc()
    finally:
        hb_task.cancel()
        active_connections[client_id].discard(websocket)
        if not active_connections[client_id]:
            del active_connections[client_id]

        try:
            await websocket.close()
        except Exception:
            pass  # Ignore further errors on close


# -------------------------------------------------------------
# Graceful shutdown
# -------------------------------------------------------------

@app.on_event("shutdown")
async def on_shutdown():
    logging.info("Shutting down. Closing remaining websockets…")
    for ws_set in active_connections.values():
        for ws in ws_set:
            try:
                await ws.close(code=1001)
            except Exception:
                pass
