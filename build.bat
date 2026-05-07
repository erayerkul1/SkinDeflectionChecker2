@echo off
set PYTHON="C:\ProgramData\anaconda3\python.exe"

echo Kullanilan Python: %PYTHON%
echo.

:: h5py kurulu mu kontrol et
%PYTHON% -c "import h5py" 2>nul
if errorlevel 1 (
    echo HATA: h5py Anaconda'da kurulu degil.
    echo Anaconda Prompt'ta su komutu calistirin:
    echo   pip install h5py
    pause
    exit /b 1
)

:: PyInstaller kurulu mu kontrol et
%PYTHON% -m PyInstaller --version 2>nul
if errorlevel 1 (
    echo PyInstaller bulunamadi, kuruluyor...
    %PYTHON% -m pip install pyinstaller
)

echo.
echo Build basliyor...
%PYTHON% -m PyInstaller displacement_extractor.spec --clean

echo.
if exist "dist\DisplacementExtractor.exe" (
    echo TAMAMLANDI: dist\DisplacementExtractor.exe olusturuldu.
) else (
    echo HATA: Exe olusturulamadi. Yukaridaki hatalara bakin.
)
pause
