#!/bin/bash
# Script to build VeloLeads macOS Application (.app & .zip)

echo "Building VeloLeads for macOS..."

# Clean old builds
rm -rf build dist

# Check Python environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "Installing/Updating requirements..."
pip install -r requirements.txt
playwright install chromium

echo "Generating User Guide PDF..."
python generate_pdf.py

if [ $? -ne 0 ]; then
    echo "PDF generation failed."
    exit 1
fi

echo "Running PyInstaller for macOS..."
pyinstaller --noconfirm --clean --onefile --windowed --name "VeloLeads" ui.py

if [ $? -ne 0 ]; then
    echo "PyInstaller build failed."
    exit 1
fi

# Package into a zip for easy distribution on macOS
echo "Packaging macOS build..."
cp VeloLeads_User_Guide.pdf dist/
cd dist
if [ -d "VeloLeads.app" ]; then
    zip -r "VeloLeads-macOS.zip" "VeloLeads.app" "VeloLeads_User_Guide.pdf"
elif [ -f "VeloLeads" ]; then
    zip "VeloLeads-macOS.zip" "VeloLeads" "VeloLeads_User_Guide.pdf"
fi
cd ..

echo ""
echo "========================================================"
echo "macOS Build Complete!"
echo "Find your Mac release in the 'dist' folder:"
echo " - dist/VeloLeads.app (Double-clickable Mac Application)"
echo " - dist/VeloLeads-macOS.zip (Contains VeloLeads.app and VeloLeads_User_Guide.pdf)"
echo "========================================================"

