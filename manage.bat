@echo off
REM SteadFast Return Scraper Manager Script for Windows

setlocal

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if "%1"=="" goto usage
if "%1"=="build" goto build
if "%1"=="start" goto start
if "%1"=="stop" goto stop
if "%1"=="restart" goto restart
if "%1"=="logs" goto logs
if "%1"=="status" goto status
if "%1"=="run" goto run
if "%1"=="clean" goto clean
goto usage

:build
echo Building Docker image...
docker-compose build
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)
echo Build completed successfully!
goto end

:start
if not exist .env (
    echo .env file not found!
    if exist .env.example (
        echo Creating .env from .env.example...
        copy .env.example .env
        echo Please edit .env file with your credentials
        exit /b 1
    ) else (
        echo .env.example not found!
        exit /b 1
    )
)
if not exist data mkdir data
echo Starting scraper...
docker-compose up -d
echo Scraper started in background
echo View logs with: manage.bat logs
goto end

:stop
echo Stopping scraper...
docker-compose down
echo Scraper stopped
goto end

:restart
echo Restarting scraper...
docker-compose restart
echo Scraper restarted
goto end

:logs
docker-compose logs -f
goto end

:status
docker-compose ps
goto end

:run
if not exist .env (
    echo .env file not found!
    if exist .env.example (
        echo Creating .env from .env.example...
        copy .env.example .env
        echo Please edit .env file with your credentials
        exit /b 1
    ) else (
        echo .env.example not found!
        exit /b 1
    )
)
if not exist data mkdir data
echo Running scraper (foreground)...
docker-compose up
goto end

:clean
echo Removing containers and images...
docker-compose down --rmi all
echo Cleanup completed
goto end

:usage
echo SteadFast Return Scraper Manager
echo.
echo Usage: %~nx0 {build^|start^|stop^|restart^|logs^|status^|run^|clean}
echo.
echo Commands:
echo   build    - Build Docker image
echo   start    - Start scraper in background
echo   stop     - Stop scraper
echo   restart  - Restart scraper
echo   logs     - View scraper logs (live)
echo   status   - Show container status
echo   run      - Run scraper in foreground
echo   clean    - Remove containers and images
exit /b 1

:end
endlocal
