@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Instale Python 3.9 o posterior desde https://www.python.org/downloads/windows/
        echo Durante la instalacion, incluya Tcl/Tk y agregue Python al PATH.
        exit /b 1
    )
    set "PYTHON_CMD=python"
) else (
    set "PYTHON_CMD=py -3"
)

if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "EnsayoTriaxial.spec"
if errorlevel 1 exit /b 1

echo.
echo Aplicacion creada: dist\EnsayoTriaxial\EnsayoTriaxial.exe
echo Distribuya la carpeta completa dist\EnsayoTriaxial, no solo el EXE.
exit /b 0
