@echo off
:: 이커머스 트렌드 대시보드 시작 스크립트
:: 터미널을 닫아도 Streamlit이 백그라운드에서 유지됩니다.

set APP_DIR=%~dp0ecommerce_market_agent
set STREAMLIT=%~dp0.venv\Scripts\streamlit.exe
set LOG_OUT=%~dp0streamlit_out.log
set LOG_ERR=%~dp0streamlit_err.log

:: 기존 Streamlit 프로세스 종료
taskkill /F /IM streamlit.exe >nul 2>&1
timeout /t 2 >nul

:: 백그라운드 실행 (창 없음, 터미널 독립)
start /B "" "%STREAMLIT%" run "%APP_DIR%\app.py" --server.port 8501 --server.headless true 1>"%LOG_OUT%" 2>"%LOG_ERR%"

timeout /t 5 >nul
echo.
echo  대시보드가 시작되었습니다: http://localhost:8501
echo  로그 파일: %LOG_OUT%
echo  이 창을 닫아도 서버는 계속 실행됩니다.
echo.
pause
