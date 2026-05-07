@echo off
echo DisplacementExtractor.exe olusturuluyor...
"C:\ProgramData\anaconda3\python.exe" -m pip install pyinstaller --quiet
"C:\ProgramData\anaconda3\python.exe" -m PyInstaller displacement_extractor.spec --clean
echo.
echo Tamamlandi! dist\DisplacementExtractor.exe dosyasi olusturuldu.
pause
