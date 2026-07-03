@echo off
echo ====================================
echo  SonarQube自动修复系统
echo ====================================
echo.

:menu
echo 请选择操作:
echo 1. 运行系统测试
echo 2. 查看系统状态
echo 3. 运行自动修复流程
echo 4. 干运行模式（测试）
echo 5. 重置处理记录
echo 6. 查看帮助
echo 7. 退出
echo.
set /p choice=请输入选项 (1-7): 

if "%choice%"=="1" goto test
if "%choice%"=="2" goto status
if "%choice%"=="3" goto run
if "%choice%"=="4" goto dryrun
if "%choice%"=="5" goto reset
if "%choice%"=="6" goto help
if "%choice%"=="7" goto exit
goto menu

:test
echo.
echo 运行系统测试...
python test_system.py
echo.
pause
goto menu

:status
echo.
echo 查看系统状态...
python cli.py status
echo.
pause
goto menu

:run
echo.
echo 运行自动修复流程...
python main.py
echo.
pause
goto menu

:dryrun
echo.
echo 干运行模式...
python cli.py run --dry-run
echo.
pause
goto menu

:reset
echo.
echo 重置处理记录...
python cli.py reset
echo.
pause
goto menu

:help
echo.
echo 查看帮助信息...
python cli.py help
echo.
pause
goto menu

:exit
echo.
echo 再见！
exit