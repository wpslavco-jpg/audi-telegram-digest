@echo off
REM Запускает дашборд управления Audi Digest. Откроется в браузере автоматически.
cd /d "%~dp0"
streamlit run dashboard.py
pause
