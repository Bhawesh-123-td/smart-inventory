@echo off
setlocal
python -m pip install --upgrade pyinstaller reportlab
pyinstaller --clean --onefile --windowed --add-data "creator_cat.png;." smart_inventory.py
echo.
echo Build complete. Your EXE is in the dist folder.
pause
