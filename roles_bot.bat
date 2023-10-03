@SETLOCAL
@ECHO OFF
REM Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
REM commands until closed.

REM Capture path of folder containing this script.
SET BatchFolder=%~dp0
REM Remove trailing slash.
SET BatchFolder=%BatchFolder:~0,-1%




REM Install missing libraries.
ECHO Installing Dependencies:
py -3 -m pip install --requirement "%BatchFolder%\requirements.txt" ^
    | FIND /V "Requirement already satisfied: "
ECHO.




REM Perform static analysis type-checking if available.
where mypy > NUL
IF NOT ERRORLEVEL 1 (
    REM Mypy is installed.
    ECHO Type Checking:

    REM Analyze Python script for data-flow/data-type mistakes using Mypy:
    REM https://github.com/python/mypy

    mypy "%BatchFolder%\roles_bot.py" ^
        --config-file "%BatchFolder%\mypy.ini" ^
        --cache-dir "%BatchFolder%\.mypy_cache"
    REM Note: Problems do not stop execution.

    ECHO.
    ECHO.
)




SET Command=py -3 "%BatchFolder%\roles_bot.py" %*
ECHO Executing: %Command%
%Command%

ECHO.
PAUSE
