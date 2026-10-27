#!/usr/bin/env python3
"""
🔍 AI Interview System - Final Verification Script
Checks all dependencies, files, and configuration before running
"""

import os
import sys
from pathlib import Path
import importlib.util

print("=" * 70)
print("🔍 AI INTERVIEW SYSTEM - FINAL VERIFICATION")
print("=" * 70)
print()

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
CHECK = '✅'
FAIL = '❌'
WARN = '⚠️'

checks_passed = 0
checks_failed = 0
checks_warning = 0

def check_item(name, passed, details=""):
    global checks_passed, checks_failed, checks_warning
    if passed is True:
        print(f"{CHECK} {GREEN}{name}: PASS{RESET}")
        checks_passed += 1
    elif passed is None:
        print(f"{WARN} {YELLOW}{name}: WARNING{RESET}")
        if details:
            print(f"   {details}")
        checks_warning += 1
    else:
        print(f"{FAIL} {RED}{name}: FAIL{RESET}")
        if details:
            print(f"   {details}")
        checks_failed += 1
    if details and passed is True:
        print(f"   {details}")

# ===== SECTION 1: Environment Variables =====
print(f"{BLUE}[1/5] Checking Environment Variables...{RESET}")
print("-" * 70)

groq_key = os.getenv("GROQ_API_KEY", "")
if groq_key:
    check_item("GROQ_API_KEY", True, f"Key found (len: {len(groq_key)} chars)")
else:
    check_item("GROQ_API_KEY", False,
               "Set with: set GROQ_API_KEY=your-key (Windows)")
print()

# ===== SECTION 2: Python Module Imports =====
print(f"{BLUE}[2/5] Checking Python Modules...{RESET}")
print("-" * 70)

required_modules = {
    'fastapi': 'Web framework',
    'whisper': 'Speech transcription (Whisper)',
    'librosa': '🎵 Audio analysis (Tone)',
    'groq': '🤖 Groq client (Scoring)',
    'numpy': 'Numerical computing',
    'scipy': 'Scientific computing',
    'multipart': 'File upload support'
}

for module_name, description in required_modules.items():
    spec = importlib.util.find_spec(module_name)
    check_item(f"{module_name}", spec is not None, description)
print()

# ===== SECTION 3: Required Files =====
print(f"{BLUE}[3/5] Checking Required Files...{RESET}")
print("-" * 70)

base_dir = Path(__file__).parent
required_files = {
    'main.py': 'FastAPI backend',
    'tone_analyzer.py': 'Tone analysis module (NEW)',
    'interview_scorer.py': 'AI scoring module (NEW)',
    'index.html': 'Frontend UI',
    'script.js': 'Frontend logic',
    'style.css': 'Styling'
}

for filename, description in required_files.items():
    file_path = base_dir / filename
    check_item(f"{filename}", file_path.exists(), description)
print()

# ===== SECTION 4: File Content Checks =====
print(f"{BLUE}[4/5] Checking File Configuration...{RESET}")
print("-" * 70)

# Check main.py for recent imports
main_py_path = base_dir / 'main.py'
with open(main_py_path, 'r') as f:
    main_content = f.read()

check_item("main.py has tone_analyzer import", 
           'from tone_analyzer import ToneAnalyzer' in main_content,
           "ToneAnalyzer class imported")
check_item("main.py has interview_scorer import", 
           'from interview_scorer import InterviewScorer' in main_content,
           "InterviewScorer class imported")
check_item("main.py /transcribe endpoint enhanced", 
           'tone_analysis = tone_analyzer.analyze_audio' in main_content,
           "Calls tone analysis in /transcribe")
check_item("main.py /transcribe returns ai_score", 
           '"ai_score": ai_score' in main_content,
           "Returns AI score in response")
print()

# Check script.js for UI updates
script_js_path = base_dir / 'script.js'
with open(script_js_path, 'r') as f:
    script_content = f.read()

check_item("script.js has displayToneAnalysis function", 
           'function displayToneAnalysis' in script_content,
           "Renders tone analysis UI")
check_item("script.js has displayAIScore function", 
           'function displayAIScore' in script_content,
           "Renders AI scores UI")
check_item("script.js completeInterview shows averages", 
           'totalContentScore / scoredAnswers' in script_content,
           "Calculates average scores in summary")
print()

# ===== SECTION 5: Feature Verification =====
print(f"{BLUE}[5/5] Verifying New Features...{RESET}")
print("-" * 70)

# Check ToneAnalyzer
tone_analyzer_path = base_dir / 'tone_analyzer.py'
with open(tone_analyzer_path, 'r') as f:
    tone_content = f.read()

feature_checks = [
    ('ToneAnalyzer class defined', 'class ToneAnalyzer:'),
    ('Pitch extraction method', '_extract_pitch_features'),
    ('Energy extraction method', '_extract_energy_features'),
    ('Speech rate estimation', '_estimate_speech_rate'),
    ('Spectral features extraction', '_extract_spectral_features'),
    ('MFCC features extraction', '_extract_mfcc_features'),
]

for feature_name, search_str in feature_checks:
    check_item(f"ToneAnalyzer: {feature_name}", search_str in tone_content)

print()

# Check InterviewScorer
scorer_path = base_dir / 'interview_scorer.py'
with open(scorer_path, 'r') as f:
    scorer_content = f.read()

scorer_checks = [
    ('InterviewScorer class defined', 'class InterviewScorer:'),
    ('Groq API integration', 'Groq'),
    ('Score generation method', 'def generate_score'),
    ('Report generation method', 'def generate_interview_report'),
    ('Tone data formatting', '_format_tone_data'),
]

for feature_name, search_str in scorer_checks:
    check_item(f"InterviewScorer: {feature_name}", search_str in scorer_content)

print()

# ===== SECTION 6: Summary =====
print("=" * 70)
print(f"VERIFICATION SUMMARY")
print("=" * 70)
print(f"{CHECK} {GREEN}Passed:{RESET} {checks_passed}")
if checks_warning > 0:
    print(f"{WARN} {YELLOW}Warnings:{RESET} {checks_warning}")
if checks_failed > 0:
    print(f"{FAIL} {RED}Failed:{RESET} {checks_failed}")
print()

# Final recommendation
if checks_failed == 0:
    if checks_warning == 0:
        print(f"{GREEN}✨ ALL CHECKS PASSED - System is ready to run!{RESET}")
        print()
        print("Next Steps:")
        print("1. Set GROQ_API_KEY if not already set")
        print("2. Run: python main.py")
        print("3. Open: http://localhost:8080")
        sys.exit(0)
    else:
        print(f"{YELLOW}⚠️  WARNINGS DETECTED - Review above before running{RESET}")
        print()
        print("Most critical warning:")
        if not groq_key:
            print("→ GROQ_API_KEY must be set for AI scoring to work")
            print("  Run: set GROQ_API_KEY=your-key")
        sys.exit(1)
else:
    print(f"{RED}❌ CRITICAL ISSUES DETECTED - Please fix above errors{RESET}")
    print()
    print("Troubleshooting:")
    if 'librosa' not in [m for m, _ in required_modules.items() if True]:
        print("→ Install librosa: pip install librosa")
    if 'groq' not in [m for m, _ in required_modules.items() if True]:
        print("→ Install groq client: pip install groq")
    sys.exit(1)
