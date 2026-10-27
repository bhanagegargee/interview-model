#!/usr/bin/env python3
"""
Verification script to check if all dependencies are installed correctly
"""

import sys
from pathlib import Path

print("\n" + "="*60)
print("🔍 AI Voice Interview - Setup Verification")
print("="*60 + "\n")

checks = {
    "✅": [],
    "❌": []
}

# Check 1: Whisper
print("Checking Whisper installation...")
try:
    import whisper
    checks["✅"].append("Whisper is installed")
    print("✅ Whisper is installed")
except ImportError:
    checks["❌"].append("Whisper NOT installed - run: pip install openai-whisper")
    print("❌ Whisper NOT installed")

# Check 2: FastAPI
print("Checking FastAPI installation...")
try:
    import fastapi
    checks["✅"].append("FastAPI is installed")
    print("✅ FastAPI is installed")
except ImportError:
    checks["❌"].append("FastAPI NOT installed - run: pip install fastapi")
    print("❌ FastAPI NOT installed")

# Check 3: Uvicorn
print("Checking Uvicorn installation...")
try:
    import uvicorn
    checks["✅"].append("Uvicorn is installed")
    print("✅ Uvicorn is installed")
except ImportError:
    checks["❌"].append("Uvicorn NOT installed - run: pip install uvicorn")
    print("❌ Uvicorn NOT installed")

# Check 4: FFmpeg
print("Checking ffmpeg installation...")
import subprocess
try:
    result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    if result.returncode == 0:
        checks["✅"].append("ffmpeg is installed and accessible")
        print("✅ ffmpeg is installed and accessible")
    else:
        checks["❌"].append("ffmpeg not found in PATH - install from: https://ffmpeg.org/download.html")
        print("❌ ffmpeg not found in PATH")
except (FileNotFoundError, subprocess.TimeoutExpired):
    checks["❌"].append("ffmpeg not found - install from: https://ffmpeg.org/download.html")
    print("❌ ffmpeg NOT installed or not in PATH")

# Check 5: Temp folder
print("Checking temp_audio folder...")
temp_dir = Path("temp_audio")
if temp_dir.exists():
    checks["✅"].append(f"temp_audio folder exists: {temp_dir.absolute()}")
    print(f"✅ temp_audio folder exists: {temp_dir.absolute()}")
else:
    checks["❌"].append("temp_audio folder does not exist")
    print("❌ temp_audio folder does not exist")

# Check 6: Main files
print("Checking main files...")
required_files = ["main.py", "script.js", "index.html", "style.css"]
for file in required_files:
    file_path = Path(file)
    if file_path.exists():
        checks["✅"].append(f"{file} exists")
        print(f"✅ {file} exists")
    else:
        checks["❌"].append(f"{file} NOT found")
        print(f"❌ {file} NOT found")

# Summary
print("\n" + "="*60)
print("📊 SUMMARY")
print("="*60)
print(f"✅ Passed: {len(checks['✅'])}")
print(f"❌ Failed: {len(checks['❌'])}")

if checks["❌"]:
    print("\n⚠️  ISSUES TO FIX:")
    for issue in checks["❌"]:
        print(f"  • {issue}")
else:
    print("\n🎉 All checks passed! You're ready to go!")

print("\n" + "="*60 + "\n")
