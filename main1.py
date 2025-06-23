from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import datetime
import traceback
import os 

app = FastAPI()
scheduler = AsyncIOScheduler()
scheduler.start()

alarm_time = None  


async def alarm_goes_off(websocket: WebSocket):
    try:
        await websocket.send_json({"type": "alarm_goes_off"})
        os.system("afplay /System/Library/Sounds/Glass.aiff") 
    except Exception as e:
        print("Alarm failed:", e)
        traceback.print_exc()


@app.websocket("/alarm/")
async def alarm(websocket: WebSocket):
    global alarm_time
    await websocket.accept()
    print("WebSocket connected.")
    try:
        while True:
            data = await websocket.receive_json()
            print("Received:", data)

            if data["type"] == "set_alarm":
                try:
                    alarm_time = datetime.datetime.strptime(
                        data["time"], "%Y-%m-%d %H:%M:%S"
                    )
                except ValueError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid time format, should be YYYY-MM-DD HH:MM:SS"
                    })
                    continue

                scheduler.add_job(
                    alarm_goes_off, 'date',
                    run_date=alarm_time,
                    args=[websocket]
                )
                await websocket.send_json({
                    "type": "set_alarm",
                    "message": f"Alarm set for {alarm_time}"
                })

            elif data["type"] == "snooze":
                if alarm_time is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No alarm is currently set."
                    })
                    continue
                snooze_time = datetime.datetime.now() + datetime.timedelta(minutes=10)
                scheduler.add_job(
                    alarm_goes_off, 'date',
                    run_date=snooze_time,
                    args=[websocket]
                )
                await websocket.send_json({
                    "type": "snooze",
                    "message": f"Alarm snoozed for {snooze_time}"
                })

            elif data["type"] == "stop_alarm":
                scheduler.remove_all_jobs()
                await websocket.send_json({
                    "type": "stop_alarm",
                    "message": "Alarm stopped"
                })
                await websocket.close()
                break

    except WebSocketDisconnect:
        print("WebSocket disconnected.")
    except Exception as e:
        print("Error in WebSocket handler:", e)
        traceback.print_exc()
