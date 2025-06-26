# Alarm-Clock-using-Fastapi-on-mac-with-fault-Tolerance
using fastapi and import the libraries , we can create the alarm clock using year, month, day , hours, minutes and seconds



git clone https://github.com/your-username/fault-tolerant-alarm.git
cd fault-tolerant-alarm
Install dependencies

pip install -r requirements.txt
Run the server


uvicorn filename:app --reload
Replace filename with the name of your Python file (e.g. alarm_clock.py).

🧪 How to Test It
Open Hoppscotch.

Choose WebSocket and connect to:

perl
ws://127.0.0.1:8000/alarm/?client_id=omar123
To set an alarm, send:

json

{
  "type": "set_alarm",
  "time": "YYYY-MM-DD HH:MM:SS"
}
Try:

Restarting the server (Ctrl+C then run uvicorn again).

Closing and reopening the WebSocket.

Checking if the alarm still fires.


