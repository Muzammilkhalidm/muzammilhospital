@echo off
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_demo
start http://127.0.0.1:8000/
python manage.py runserver
pause
