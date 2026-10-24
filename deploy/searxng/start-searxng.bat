@echo off
chcp 65001 >nul
echo ============================================
echo  启动 ATRI 本地 SearXNG 搜索服务
echo ============================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Docker。请先安装 Docker Desktop：
    echo   https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

cd /d "%~dp0"

echo 正在启动 SearXNG 容器...
docker compose -f docker-compose.yml up -d
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请检查 Docker 是否已运行。
    pause
    exit /b 1
)

echo.
echo [完成] SearXNG 已启动，访问 http://127.0.0.1:8888 验证。
echo 请确认 .env 中已配置：
echo   ATRI_SEARXNG_INSTANCES=http://127.0.0.1:8888
echo.
pause
