# AI-Powered Auto-Interview System

An intelligent, fully localized technical and behavioral interview simulation model. This application creates a personalized, automated interview experience that asks dynamic questions, transcribes the user's spoken answers, and evaluates tone, body language, and verbal communication skills using localized machine learning and Large Language Models (LLMs).

## Features
- **Dynamic Question Generation**: Creates targeted interview questions based on the candidate's profile and CV using the local Ollama LLM.
- **Three-question interviews**: The next question starts after each recording is saved. Answer scoring continues in the background, and the final report waits for all analysis to finish.
- **Audio Transcription & Tone Analysis**: Transcribes answers offline via OpenAI's Whisper model (`base` size) and uses `librosa` to analyze speech rates, pitch, and energy.
- **AI Scoring & Feedback**: Evaluates the transcribed answers locally on your machine using Ollama (`llama3.1:8b` by default).
- **Body Language & Video Analysis**: Employs backend OpenCV & MediaPipe techniques to evaluate eye contact, shoulder alignment, and spine angle. 
- **Real-Time Distraction Alert**: The browser dynamically runs a frontend MediaPipe face detection model from the camera feed while recording, instantly flashing an alert if there are multiple people or zero people in the frame in real-time.

---

## Architecture Overview
The system has been completely decoupled from cloud APIs (Groq) to ensure data privacy and to avoid unexpected network or quote billing errors.
1. **Frontend**: HTML/JS dashboard hosted via a simple HTTP server (default port `3000`).
2. **Backend**: Python FastAPI endpoint (default port `8000`) managing heavy model inference requests via `.webm` audio/video file uploads. 
3. **LLM Engine**: Desktop Ollama instance actively running LLama 3.

---

## Getting Started

### Prerequisites
1. **Python 3.9+** installed locally.
2. **FFMPEG** installed on your system. It must be accessible from your system's PATH. (Can be downloaded from https://ffmpeg.org/download.html).
3. **Ollama** installed on your system.
    - Start it in a background terminal by pulling/running the model at least once:
      ```powershell
      ollama pull llama3.1:8b
      ```

### 1. Backend Setup
Navigate to the root directory `AI-powered-interview-model/` and set up the Python environment:

```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Navigate into the backend folder and install dependencies
cd backend
pip install -r requirements.txt
```

### 2. Start the Backend
```powershell
# While the venv is activated and you are in the backend/ folder:
python main.py
```
If you use a different installed Ollama model, set `OLLAMA_MODEL` before starting the backend (for example, `$env:OLLAMA_MODEL = "qwen2.5-coder:7b"`). The default question-generation timeout is 180 seconds; set `OLLAMA_QUESTION_TIMEOUT` to adjust it for a slower machine.
Answer and video scoring can take longer on a local CPU. Their default Ollama timeouts are 240 seconds; adjust them with `OLLAMA_SCORING_TIMEOUT` and `OLLAMA_VIDEO_TIMEOUT` if needed.
*Note: The first time it runs, the Whisper model weights (~74 MB) will be securely compiled/downloaded locally. Do not cancel the script while it reads `Loading Whisper model...`.*

### 3. Start the Frontend 
Open a new separate terminal, navigate to this project's root folder, and start a basic HTTP web server from inside the `frontend` directory:
```powershell
# Enter the frontend folder and start the server on port 3000
cd frontend
python -m http.server 3000
```

### 4. Running the App
1. Open your browser and navigate to exactly `http://localhost:3000`.
2. Allow camera and microphone permissions when prompted by your browser securely.
3. Enter your professional details/skills, and successfully start the AI interview session!

---

## Important Usage Note
Since all Whisper Transcription and AI Response generation logic operates seamlessly offline on your local CPU (or GPU depending on your hardware config):
- **Processing Time:** While the camera records, it buffers the video directly. Processing happens *after* you finish recording. Whisper transcription, answer scoring, and video assessment run in sequence and can take several minutes on a local CPU. Keep the interview page open while it shows **"Processing..."**.
