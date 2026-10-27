let questionIndex = 0;
let mediaRecorder = null;
let audioChunks = [];
let stream = null;
let videoStream = null;
let videoRecorder = null;
let videoChunks = [];
let permissionStream = null;  // Held open from the one-time camera permission request

let faceDetection = null;
let isDetectingFaces = false;
let faceDetectionInFlight = false;

let interviewActive = false;
let answers = [];
const pendingAnalyses = new Set();
let isCompleting = false;
let recordingTimeout;
let startBtn, skipBtn, stopBtn, statusText, questionText, answerText, progressText, indicator;
let toneAnalysisBox, toneAnalysisContent, scoreBox, scoreContent, feedbackBox, summaryContent;
let toneReportBox, toneReportContent;
let statusPill;

const BACKEND_URL = window.BACKEND_URL || "http://127.0.0.1:8000";

// MAX_RECORDING_TIME is now a *fallback only*.
// Each question supplies its own timing_ms from the backend.
// The hardcoded 30 s is no longer used during normal flow.
const FALLBACK_RECORDING_TIME_MS = window.MAX_RECORDING_TIME || 60_000;

// Holds the recording time for the question currently being answered.
// Set in askNextQuestion() from the server response, used in startRecording().
let currentQuestionTimingMs = FALLBACK_RECORDING_TIME_MS;

// ── Pull candidate info stored by register.html ────────────────
const CANDIDATE_EMAIL     = sessionStorage.getItem('candidateEmail') || '';
const CANDIDATE_NAME      = sessionStorage.getItem('candidateName')  || 'Candidate';
const GENERATED_QUESTIONS = JSON.parse(sessionStorage.getItem('generatedQuestions') || '[]');
const GENERATED_TIMINGS   = JSON.parse(sessionStorage.getItem('generatedTimings') || '[]');
const TOTAL_QUESTIONS     = Math.min(GENERATED_QUESTIONS.length || 3, 3);

// ── Orb state manager ────────────────────────────────────────────
function setOrb(state, label) {
    const orb = document.getElementById('aiOrb');
    const lbl = document.getElementById('orbLabel');
    if (!orb || !lbl) return;
    orb.className = 'ai-orb';
    lbl.className = 'orb-label';
    if (state === 'idle') {
        orb.classList.add('orb-idle');
        lbl.textContent = label || 'Ready';
    } else if (state === 'talking') {
        orb.classList.add('orb-talking');
        lbl.classList.add('talking');
        lbl.textContent = label || 'AI Speaking…';
    } else if (state === 'recording') {
        orb.classList.add('orb-recording');
        lbl.classList.add('recording');
        lbl.textContent = label || 'Listening…';
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    startBtn        = document.getElementById('startBtn');
    skipBtn         = document.getElementById('skipBtn');
    stopBtn         = document.getElementById('stopBtn');
    statusText      = document.getElementById('statusText');
    questionText    = document.getElementById('questionText');
    answerText      = document.getElementById('answerText');
    progressText    = document.getElementById('progressText');
    indicator       = document.getElementById('recordingIndicator');
    toneAnalysisBox     = document.getElementById('toneAnalysisBox');
    toneAnalysisContent = document.getElementById('toneAnalysisContent');
    scoreBox            = document.getElementById('scoreBox');
    scoreContent        = document.getElementById('scoreContent');
    feedbackBox         = document.getElementById('feedbackBox');
    summaryContent      = document.getElementById('summaryContent');
    toneReportBox       = document.getElementById('toneReportBox');
    toneReportContent   = document.getElementById('toneReportContent');
    statusPill = document.getElementById('statusPill');

    // Greet candidate if name available
    if (CANDIDATE_NAME && CANDIDATE_NAME !== 'Candidate') {
        const heroSub = document.querySelector('.hero-sub');
        if (heroSub) heroSub.textContent =
            `Welcome, ${CANDIDATE_NAME}. Your personalised interview questions are ready. Answer out loud while being recorded.`;
    }

    // Update total question count in progress display
    if (progressText) progressText.textContent = `Q 0 / ${TOTAL_QUESTIONS}`;
    const progLabel = document.getElementById('progressLabel');
    if (progLabel) progLabel.textContent = `Question 0 of ${TOTAL_QUESTIONS}`;

    if (startBtn) startBtn.disabled = false;
    if (skipBtn)  skipBtn.disabled  = true;
    if (stopBtn)  stopBtn.disabled  = true;

    // ── Request camera + mic permission ONCE upfront ──────────────
    try {
        permissionStream = await navigator.mediaDevices.getUserMedia({
            audio: true,
            video: { width: 1280, height: 720, facingMode: 'user' }
        });
        // Keep tracks alive (will be reused in startRecording)
        console.log('✅ Camera & microphone permissions granted');
    } catch (err) {
        console.warn('⚠️ Could not get camera permission upfront:', err.message);
        permissionStream = null;
    }

    // ── Initialize MediaPipe Face Detection ──────────────
    try {
        faceDetection = new FaceDetection({
            locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection/${file}`
        });

        // Keep compatibility with different MediaPipe builds.
        try {
            faceDetection.setOptions({
                modelSelection: 0,
                minDetectionConfidence: 0.5
            });
        } catch (_) {
            faceDetection.setOptions({
                model: 'short',
                minDetectionConfidence: 0.5
            });
        }

        faceDetection.onResults(onFaceResults);
    } catch (e) {
        console.warn('⚠️ Face detection init failed; distraction alerts won\'t run:', e);
    }
});

function onFaceResults(results) {
    const alertBox = document.getElementById('distractionAlert');
    if (!isDetectingFaces || !alertBox) return;
    
    if (!results.detections || results.detections.length !== 1) {
        alertBox.style.display = 'block';
    } else {
        alertBox.style.display = 'none';
    }
}

function processVideoFrame() {
    const video = document.getElementById('videoPreview');

    if (!isDetectingFaces) return;

    // Keep polling while recording so detection starts as soon as video is ready.
    if (!video || video.paused || video.ended || video.readyState < 2 || !faceDetection) {
        setTimeout(processVideoFrame, 250);
        return;
    }

    if (!faceDetectionInFlight) {
        faceDetectionInFlight = true;
        faceDetection
            .send({ image: video })
            .catch((e) => console.warn('Face track err', e))
            .finally(() => {
                faceDetectionInFlight = false;
            });
    }

    setTimeout(processVideoFrame, 250); // ~4 checks/second
}

function setPill(state, text) {
    if (!statusPill) return;
    statusPill.className = 'status-pill ' + state;
    statusPill.textContent = text;
}

// ═══════════════════════════════════════════════════════════════════
// DISPLAY HELPERS  (unchanged from original)
// ═══════════════════════════════════════════════════════════════════

function rateColor(value, max = 10, inverted = false) {
    const ratio = value / max;
    if (inverted) {
        if (ratio < 0.05) return '#34d399';
        if (ratio < 0.15) return '#fbbf24';
        return '#f87171';
    }
    if (ratio >= 0.75) return '#34d399';
    if (ratio >= 0.50) return '#fbbf24';
    return '#f87171';
}

function scoreBadge(value) {
    if (value >= 8.5) return { label: 'Excellent',       color: '#34d399' };
    if (value >= 7.0) return { label: 'Good',            color: '#6ee7b7' };
    if (value >= 5.5) return { label: 'Average',         color: '#fbbf24' };
    if (value >= 4.0) return { label: 'Below Average',   color: '#fb923c' };
    return               { label: 'Needs Work',          color: '#f87171' };
}

function scoreCard(label, value, max, inverted = false, meaning = '') {
    const color = rateColor(value, max, inverted);
    const pct   = Math.round((value / max) * 100);
    const displayVal = typeof value === 'number'
        ? (max === 10 ? value.toFixed(1) + ' / 10' : value.toFixed(1) + '%')
        : value;
    const badge = inverted
        ? (pct < 5 ? { label: 'Excellent', color: '#34d399' } : pct < 15 ? { label: 'Moderate', color: '#fbbf24' } : { label: 'High', color: '#f87171' })
        : scoreBadge(value);

    return `
    <div style="flex:1; min-width:140px; padding:14px 16px;
                background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
                border-radius:12px; border-top:3px solid ${color};">
        <div style="font-size:11px; letter-spacing:1.5px; text-transform:uppercase;
                    color:rgba(255,255,255,0.4); margin-bottom:8px;">${label}</div>
        <div style="font-size:26px; font-weight:800; color:${color}; line-height:1;">${displayVal}</div>
        <div style="background:rgba(0,0,0,0.2); border-radius:4px; height:5px; margin:8px 0; overflow:hidden;">
            <div style="width:${pct}%; height:100%; background:${color}; border-radius:4px; transition:width .8s ease;"></div>
        </div>
        <div style="display:inline-block; font-size:10px; font-weight:700; letter-spacing:.8px;
                    padding:2px 8px; border-radius:100px;
                    background:${badge.color}22; color:${badge.color}; border:1px solid ${badge.color}44;">
            ${badge.label}
        </div>
        ${meaning ? `<div style="font-size:11px; color:rgba(255,255,255,0.35); margin-top:6px; line-height:1.4;">${meaning}</div>` : ''}
    </div>`;
}

function metricRow(icon, label, value, display, interpretation, bg = false) {
    return `
    <tr style="${bg ? 'background:rgba(255,255,255,0.02);' : ''}">
        <td style="padding:10px 14px; width:180px;">
            <span style="font-size:14px;">${icon}</span>
            <span style="margin-left:6px; color:rgba(255,255,255,0.75); font-size:13px;">${label}</span>
        </td>
        <td style="padding:10px 14px; text-align:right; font-family:'IBM Plex Mono',monospace;
                   font-weight:700; font-size:14px; color:${value}; white-space:nowrap;">${display}</td>
        <td style="padding:10px 14px; font-size:12px; color:rgba(255,255,255,0.5); line-height:1.5;">${interpretation}</td>
    </tr>`;
}

function sectionBlock(icon, title, content, accent) {
    return `
    <div style="margin-bottom:16px; border-radius:0 10px 10px 0;
                border-left:3px solid ${accent}; background:rgba(255,255,255,0.025);
                padding:14px 16px;">
        <div style="font-size:12px; font-weight:700; letter-spacing:1px; text-transform:uppercase;
                    color:${accent}; margin-bottom:8px;">${icon}&nbsp; ${title}</div>
        <div style="font-size:13px; line-height:1.75; color:rgba(255,255,255,0.75);">${content}</div>
    </div>`;
}

function warmBulletList(items) {
    if (!items || items.length === 0) return '<p style="color:rgba(255,255,255,0.3);font-size:13px;">None noted.</p>';
    return `<ul style="list-style:none; padding:0; margin:0;">
        ${items.map(i => `
        <li style="display:flex; gap:10px; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);
                   font-size:13px; line-height:1.6; color:rgba(255,255,255,0.7);">
            <span style="flex-shrink:0; color:rgba(255,255,255,0.25);">›</span>
            <span>${i}</span>
        </li>`).join('')}
    </ul>`;
}

function interpretContent(v)    { return v>=8?`You scored <strong style="color:#34d399">${v.toFixed(1)}/10</strong> — your answers were relevant, specific, and clearly addressed what was asked.`:v>=6?`You scored <strong style="color:#fbbf24">${v.toFixed(1)}/10</strong> — on the right track, though adding more specific examples would strengthen your answers.`:v>=4?`You scored <strong style="color:#fb923c">${v.toFixed(1)}/10</strong> — some points connected to the question, but the core could be more focused.`:`You scored <strong style="color:#f87171">${v.toFixed(1)}/10</strong> — answers didn't closely address what was asked. Practising the STAR method would help.`; }
function interpretTone(v)       { return v>=8?`Tone score: <strong style="color:#34d399">${v.toFixed(1)}/10</strong> — you spoke clearly with good expression. Sounded engaged and professional.`:v>=6?`Tone score: <strong style="color:#fbbf24">${v.toFixed(1)}/10</strong> — generally good. Varying your pace would take this higher.`:v>=4?`Tone score: <strong style="color:#fb923c">${v.toFixed(1)}/10</strong> — moments where tone felt flat or rushed. Try practising with a recording.`:`Tone score: <strong style="color:#f87171">${v.toFixed(1)}/10</strong> — vocal delivery made it harder for the message to land. Daily reading out loud can help.`; }
function interpretConfidence(v) { return v>=8?`Confidence: <strong style="color:#34d399">${v.toFixed(1)}/10</strong> — you came across as assured and composed.`:v>=6?`Confidence: <strong style="color:#fbbf24">${v.toFixed(1)}/10</strong> — reasonably confident. The more you practise, the more natural it feels.`:v>=4?`Confidence: <strong style="color:#fb923c">${v.toFixed(1)}/10</strong> — noticeable nervousness. Mock interviews like this one are exactly how you improve.`:`Confidence: <strong style="color:#f87171">${v.toFixed(1)}/10</strong> — uncertainty came through clearly. Confidence is a skill — daily practice builds it fast.`; }
function interpretFiller(v)     { return v<3?`<strong style="color:#34d399">${v.toFixed(1)}%</strong> filler rate — almost none! Clean, polished speech.`:v<8?`<strong style="color:#6ee7b7">${v.toFixed(1)}%</strong> filler rate — small number of fillers. You're in good shape.`:v<15?`<strong style="color:#fbbf24">${v.toFixed(1)}%</strong> filler rate — fillers appeared frequently. Try replacing them with a short silent pause.`:`<strong style="color:#f87171">${v.toFixed(1)}%</strong> filler rate — quite high. Record yourself and count fillers — awareness alone drops the rate significantly.`; }
function interpretFumble(v)     { return v<2?`<strong style="color:#34d399">${v.toFixed(1)}%</strong> fumble rate — very clean delivery. Well done.`:v<5?`<strong style="color:#fbbf24">${v.toFixed(1)}%</strong> fumble rate — a few small hesitations. Normal in live interviews.`:`<strong style="color:#f87171">${v.toFixed(1)}%</strong> fumble rate — noticeable stumbling. Try pausing 2 seconds to organise your thought before you start.`; }
function interpretWords(v)      { return v>100?`<strong style="color:#34d399">${v} words</strong> — a well-developed, detailed answer.`:v>50?`<strong style="color:#fbbf24">${v} words</strong> — reasonable. Aim for slightly more detail.`:v>20?`<strong style="color:#fb923c">${v} words</strong> — on the brief side. Expand with examples or context.`:`<strong style="color:#f87171">${v} words</strong> — very short. 60–80 words per answer makes a big difference.`; }

// ═══════════════════════════════════════════════════════════════════
// PER-QUESTION: score panel
// ═══════════════════════════════════════════════════════════════════
function displayAIScore(aiScore) {
    try {
        const overall    = Number(aiScore.overall_score    || 0);
        const content    = Number(aiScore.content_score    || 0);
        const tone       = Number(aiScore.tone_score       || 0);
        const confidence = Number(aiScore.confidence_score || 0);
        const fillerRate = Number(aiScore.filler_word_rate || 0);
        const fumbleRate = Number(aiScore.fumble_rate      || 0);

        const methodBadge = aiScore.scoring_method === 'ai'
            ? `<span style="padding:3px 10px; border-radius:100px; font-size:11px; font-weight:700;
                           background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.3);
                           color:#34d399; font-family:'IBM Plex Mono',monospace;">✦ AI-Scored</span>`
            : `<span style="padding:3px 10px; border-radius:100px; font-size:11px; font-weight:700;
                           background:rgba(251,191,36,0.12); border:1px solid rgba(251,191,36,0.3);
                           color:#fbbf24; font-family:'IBM Plex Mono',monospace;">⚙ Rule-Based Score</span>`;

        let html = `
        <div style="margin-bottom:12px; display:flex; align-items:center; gap:8px;">${methodBadge}</div>
        <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:20px;">
            ${scoreCard('Content',    content,    10, false, 'How well the answer addressed the question')}
            ${scoreCard('Tone',       tone,       10, false, 'Vocal delivery & expression quality')}
            ${scoreCard('Overall',    overall,    10, false, 'Combined performance score')}
            ${scoreCard('Confidence', confidence, 10, false, 'Assurance & composure detected')}
            ${scoreCard('Filler Rate', fillerRate, 100, true, 'Lower is better')}
            ${scoreCard('Fumble Rate', fumbleRate, 20, true, 'Lower is better')}
        </div>`;

        if (aiScore.filler_words_found?.length)
            html += sectionBlock('🗣️', 'Filler Words Found',
                `<div style="margin-bottom:8px;">
                    ${aiScore.filler_words_found.map(w =>
                        `<span style="display:inline-block; margin:3px; padding:3px 10px;
                                      background:rgba(251,191,36,0.12); border:1px solid rgba(251,191,36,0.25);
                                      border-radius:100px; font-size:12px; color:#fbbf24;
                                      font-family:'IBM Plex Mono',monospace;">${w}</span>`
                    ).join('')}
                </div>
                <p style="font-size:12px; color:rgba(255,255,255,0.4); margin:0;">
                    ${aiScore.filler_word_count} filler(s) out of ${aiScore.word_count} total words.
                </p>`, '#fbbf24');

        if (aiScore.content_correctness) html += sectionBlock('📋', 'Content Correctness',  aiScore.content_correctness, '#38bdf8');
        if (aiScore.sentence_quality)    html += sectionBlock('📝', 'Sentence Quality',      aiScore.sentence_quality,    '#a78bfa');
        if (aiScore.voice_summary)       html += sectionBlock('🎙️', 'Vocal Delivery',        aiScore.voice_summary,       '#22d3ee');
        if (aiScore.strengths?.length)   html += sectionBlock('✅', 'What You Did Well',     warmBulletList(aiScore.strengths),   '#34d399');
        if (aiScore.weaknesses?.length)  html += sectionBlock('⚠️', 'Areas for Attention',   warmBulletList(aiScore.weaknesses),  '#f87171');
        if (aiScore.improvements?.length)html += sectionBlock('📈', 'Steps to Improve',      warmBulletList(aiScore.improvements),'#fb923c');
        if (aiScore.communication_comment) html += sectionBlock('💬', 'Communication Assessment', aiScore.communication_comment, '#0dcaf0');

        scoreBox.style.display = 'block';
        scoreContent.innerHTML = html;
    } catch (e) { console.error('Error displaying AI score:', e); }
}

// ═══════════════════════════════════════════════════════════════════
// INTERVIEW FLOW
// ═══════════════════════════════════════════════════════════════════
function startInterview() {
    if (isCompleting) return;
    interviewActive = true;
    answers = [];
    pendingAnalyses.clear();
    questionIndex = 0;

    if (startBtn) startBtn.disabled = true;
    if (skipBtn)  skipBtn.disabled  = false;
    if (stopBtn)  stopBtn.disabled  = false;

    // Hide hero, show orb
    const hero = document.getElementById('heroSection');
    const orbSection = document.getElementById('aiOrbSection');
    if (hero) hero.style.display = 'none';
    if (orbSection) orbSection.style.display = 'block';
    setOrb('idle', 'Starting…');

    if (feedbackBox)     feedbackBox.style.display     = 'none';
    if (toneAnalysisBox) toneAnalysisBox.style.display = 'none';
    if (scoreBox)        scoreBox.style.display        = 'none';
    if (toneReportBox)   toneReportBox.style.display   = 'none';

    statusText && (statusText.innerText = 'Starting interview…');
    setPill('active', 'ACTIVE');
    askNextQuestion();
}

async function skipQuestion() {
    if (!interviewActive) return;
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        clearTimeout(recordingTimeout);
        mediaRecorder.stop();
        if (videoRecorder && videoRecorder.state === 'recording') videoRecorder.stop();
        if (stream) stream.getTracks().forEach(t => t.stop());
        indicator.classList.remove('recording');
    }
    window.speechSynthesis?.cancel();
    answers.push({ question: questionText.innerText, answer: '(Skipped)' });
    questionIndex++;
    if (questionIndex >= TOTAL_QUESTIONS) completeInterview();
    else await askNextQuestion();
}

function stopInterview() {
    if (confirm('Are you sure you want to end the interview early?')) {
        interviewActive = false;
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            clearTimeout(recordingTimeout);
            mediaRecorder.stop();
            indicator.classList.remove('recording');
        }
        if (videoRecorder && videoRecorder.state === 'recording') videoRecorder.stop();
        window.speechSynthesis.cancel();
        if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
        completeInterview();
    }
}

async function askNextQuestion() {
    if (!interviewActive) return;
    try {
        const requestedIndex = questionIndex;
        let data;
        if (GENERATED_QUESTIONS[requestedIndex]) {
            data = {
                question: GENERATED_QUESTIONS[requestedIndex],
                timing_ms: GENERATED_TIMINGS[requestedIndex],
                is_last: requestedIndex === TOTAL_QUESTIONS - 1
            };
        } else {
            statusText.innerText = 'Fetching question…';
            const url = new URL(`${BACKEND_URL}/get-question`);
            url.searchParams.set('question_number', requestedIndex);
            if (CANDIDATE_EMAIL) url.searchParams.set('candidate_email', CANDIDATE_EMAIL);
            const response = await fetch(url.toString(), { method: 'POST' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            data = await response.json();
        }
        if (!interviewActive || questionIndex !== requestedIndex) return;

        // ── Store the AI-predicted timing for this question ──────────
        // Timings are cached from registration, with a backend fallback for direct visits.
        // Fall back to FALLBACK_RECORDING_TIME_MS if the field is missing.
        currentQuestionTimingMs = (data.timing_ms && data.timing_ms > 0)
            ? data.timing_ms
            : FALLBACK_RECORDING_TIME_MS;

        const timingSeconds = Math.round(currentQuestionTimingMs / 1000);
        console.log(`⏱ Q${questionIndex + 1} timing: ${timingSeconds}s (${currentQuestionTimingMs}ms)`);

        questionText.innerText = data.question;
        answerText.innerText   = '';
        if (skipBtn) skipBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = false;
        progressText.innerText = `Q ${questionIndex + 1} / ${TOTAL_QUESTIONS}`;

        const progLabel = document.getElementById('progressLabel');
        if (progLabel) progLabel.textContent = `Question ${questionIndex + 1} of ${TOTAL_QUESTIONS}`;

        // Show timing hint next to status
        const timeHint = `⏱ ${timingSeconds}s to answer`;
        statusText.innerText = data.is_last
            ? `Final question — ${timeHint}`
            : `Listen to the question… (${timeHint})`;

        await speakQuestion(data.question);
        await new Promise(r => setTimeout(r, 500));
        if (interviewActive && questionIndex === requestedIndex) await startRecording();
    } catch (error) {
        console.error('❌ Error fetching question:', error);
        statusText.innerText = 'Error: Could not connect to backend';
        alert('Backend connection failed. Make sure the FastAPI server is running on port 8000.');
        resetInterview();
    }
}

function speakQuestion(text) {
    return new Promise((resolve) => {
        try {
            if (!window.speechSynthesis) { setTimeout(resolve, 2000); return; }
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 0.9; utterance.pitch = 1.0; utterance.volume = 1.0;
            let hasEnded = false;
            utterance.onstart = () => {
                statusText.innerText = '🔊 Listening to question…';
                setOrb('talking', 'AI Speaking…');
            };
            utterance.onend   = () => {
                hasEnded = true;
                setOrb('idle', 'Your turn…');
                resolve();
            };
            utterance.onerror = () => { setOrb('idle', 'Your turn…'); resolve(); };
            window.speechSynthesis.speak(utterance);
            setTimeout(() => { if (!hasEnded) { setOrb('idle', 'Your turn…'); resolve(); } }, 10000);
        } catch (e) { setOrb('idle', 'Your turn…'); resolve(); }
    });
}

async function startRecording() {
    try {
        // Reuse the upfront permission stream if still active, else request again
        if (permissionStream && permissionStream.active) {
            stream = permissionStream;
        } else {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: { width: 1280, height: 720, facingMode: 'user' }
            });
            permissionStream = stream;
        }

        const videoPreview = document.getElementById('videoPreview');
        const videoCard    = document.getElementById('videoPreviewCard');
        if (videoPreview && videoCard) {
            videoPreview.srcObject = stream;
            videoCard.style.display = 'block';
            try {
                await videoPreview.play();
            } catch (e) {
                console.warn('Video preview play() delayed:', e?.message || e);
            }
        }

        const audioTrack = stream.getAudioTracks()[0];
        const videoTrack = stream.getVideoTracks()[0];

        mediaRecorder  = new MediaRecorder(new MediaStream([audioTrack]),               { mimeType: 'audio/webm' });
        videoRecorder  = new MediaRecorder(new MediaStream([videoTrack, audioTrack]),   { mimeType: 'video/webm' });

        audioChunks = [];
        videoChunks = [];

        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
        videoRecorder.ondataavailable = e => { if (e.data.size > 0) videoChunks.push(e.data); };

        mediaRecorder.onstart = () => {
            indicator.classList.add('recording');
            const timingSeconds = Math.round(currentQuestionTimingMs / 1000);
            statusText.innerText = `🎤🎥 Recording… (${timingSeconds}s limit)`;
            setPill('recording', 'REC ●');
            setOrb('recording', 'Listening…');

            // Use the per-question AI-predicted timing instead of a fixed 30s
            recordingTimeout = setTimeout(() => {
                if (mediaRecorder && mediaRecorder.state === 'recording') stopRecording();
            }, currentQuestionTimingMs);

            // Start processing faces
            isDetectingFaces = true;
            faceDetectionInFlight = false;
            processVideoFrame();
        };

        mediaRecorder.start();
        videoRecorder.start();
    } catch (error) {
        console.error('❌ Recording error:', error);
        statusText.innerText = 'Error: Could not access camera/microphone';
        alert('Camera/microphone access error. Please check permissions.');
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        const completedIndex = questionIndex;
        const completedQuestion = questionText.innerText;
        const videoIsRecording = videoRecorder && videoRecorder.state === 'recording';
        let recordersPending = videoIsRecording ? 2 : 1;
        const recorderStopped = () => {
            recordersPending--;
            if (recordersPending === 0) sendMediaToBackend(completedIndex, completedQuestion);
        };
        mediaRecorder.addEventListener('stop', recorderStopped, { once: true });
        if (videoIsRecording) videoRecorder.addEventListener('stop', recorderStopped, { once: true });
        clearTimeout(recordingTimeout);
        mediaRecorder.stop();
        if (videoIsRecording) videoRecorder.stop();
        indicator.classList.remove('recording');
        statusText.innerText = 'Saving answer and preparing the next question…';
        setOrb('idle', 'Saving answer…');
        if (skipBtn) skipBtn.disabled = true;
        if (stopBtn) stopBtn.disabled = true;

        const videoCard = document.getElementById('videoPreviewCard');
        if (videoCard) videoCard.style.display = 'none';

        isDetectingFaces = false;
        faceDetectionInFlight = false;
        const alertBox = document.getElementById('distractionAlert');
        if (alertBox) alertBox.style.display = 'none';

    }
}

function sendMediaToBackend(completedIndex, completedQuestion) {
    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
    const videoBlob = videoChunks.length > 0 ? new Blob(videoChunks, { type: 'video/webm' }) : null;
    const entry = { question: completedQuestion, answer: '(Analysis pending)' };
    answers[completedIndex] = entry;

    if (audioBlob.size > 0) {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'answer.webm');
        if (videoBlob) formData.append('video', videoBlob, 'answer_video.webm');
        formData.append('question', completedQuestion);
        formData.append('candidate_email', CANDIDATE_EMAIL || '');
        formData.append('question_number', String(completedIndex));

        const analysis = (async () => {
            try {
                const response = await fetch(`${BACKEND_URL}/analyze-answer`, { method: 'POST', body: formData });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                Object.assign(entry, {
                    answer: data.transcript || '(No speech detected)',
                    tone_analysis: data.tone_analysis,
                    ai_score: data.ai_score,
                    video_analysis: data.video_analysis
                });
            } catch (error) {
                console.error(`Error processing question ${completedIndex + 1}:`, error);
                entry.answer = '(Processing failed)';
                entry.error = error.message;
            }
        })();
        pendingAnalyses.add(analysis);
        analysis.finally(() => {
            pendingAnalyses.delete(analysis);
            if (isCompleting && pendingAnalyses.size > 0) {
                statusText.innerText = `Finishing ${pendingAnalyses.size} answer analysis request(s)…`;
            }
        });
    } else {
        entry.answer = '(No audio detected)';
    }

    if (interviewActive) {
        questionIndex = completedIndex + 1;
        if (questionIndex >= TOTAL_QUESTIONS) completeInterview();
        else askNextQuestion();
    }
}

function displayToneAnalysis(toneAnalysis) {
    try {
        let html = "<ul style='list-style:none; padding:0; font-size:13px; line-height:2;'>";
        const pitch = toneAnalysis.pitch_features || {};
        if (pitch.mean_pitch) {
            const desc = pitch.mean_pitch < 150 ? 'Deep, authoritative'
                       : pitch.mean_pitch < 250 ? 'Natural, neutral' : 'High, energetic';
            html += `<li>🎵 <strong>Pitch:</strong> ${pitch.mean_pitch.toFixed(0)} Hz — ${desc}</li>`;
        }
        const energy = toneAnalysis.energy_features || {};
        if (energy.energy_consistency !== undefined)
            html += `<li>⚡ <strong>Volume Consistency:</strong> ${(energy.energy_consistency*100).toFixed(0)}%</li>`;
        const speech = toneAnalysis.speech_rate_estimate || {};
        if (speech.estimated_wpm)
            html += `<li>🗣️ <strong>Speech Rate:</strong> ${speech.estimated_wpm.toFixed(0)} WPM (${speech.speech_rate_category})</li>`;
        const spectral = toneAnalysis.spectral_features || {};
        if (spectral.spectral_centroid_mean)
            html += `<li>📈 <strong>Voice Clarity:</strong> ${spectral.spectral_centroid_mean.toFixed(0)} Hz</li>`;
        html += '</ul>';
        toneAnalysisBox.style.display = 'block';
        toneAnalysisContent.innerHTML = html;
    } catch (e) { console.error('Error displaying tone analysis:', e); }
}

function displayVideoAnalysis(videoData) {
    if (!videoData || videoData.error) return;
    const assessment = videoData.assessment || {};
    const metrics    = videoData.raw_metrics || {};
    const method     = videoData.analysis_method || 'unknown';

    let html = `
    <div style="margin-bottom:12px;">
        <span style="padding:4px 12px; border-radius:100px; font-size:11px; font-weight:700;
                     background:${method==='ai'?'rgba(52,211,153,0.12)':'rgba(251,191,36,0.12)'};
                     border:1px solid ${method==='ai'?'rgba(52,211,153,0.3)':'rgba(251,191,36,0.3)'};
                     color:${method==='ai'?'#34d399':'#fbbf24'};
                     font-family:'IBM Plex Mono',monospace;">
            ${method==='ai'?'✦ AI-Analyzed':'⚙ Rule-Based Analysis'}
        </span>
    </div>
    <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:20px;">
        <div style="padding:12px 16px; background:rgba(255,255,255,0.03); border-radius:10px; border-left:3px solid #38bdf8;">
            <div style="font-size:11px; color:rgba(255,255,255,0.4); margin-bottom:4px;">EYE CONTACT</div>
            <div style="font-size:24px; font-weight:800; color:#38bdf8;">${((metrics.eye_contact_rate||0)*100).toFixed(1)}%</div>
        </div>
        <div style="padding:12px 16px; background:rgba(255,255,255,0.03); border-radius:10px; border-left:3px solid #a78bfa;">
            <div style="font-size:11px; color:rgba(255,255,255,0.4); margin-bottom:4px;">SHOULDER ALIGNMENT</div>
            <div style="font-size:24px; font-weight:800; color:#a78bfa;">${(metrics.avg_shoulder_alignment||0).toFixed(1)}°</div>
        </div>
        <div style="padding:12px 16px; background:rgba(255,255,255,0.03); border-radius:10px; border-left:3px solid #22d3ee;">
            <div style="font-size:11px; color:rgba(255,255,255,0.4); margin-bottom:4px;">SPINE ANGLE</div>
            <div style="font-size:24px; font-weight:800; color:#22d3ee;">${(metrics.avg_spine_angle||0).toFixed(1)}°</div>
        </div>
        ${assessment.confidence_projection_score?`
        <div style="padding:12px 16px; background:rgba(255,255,255,0.03); border-radius:10px; border-left:3px solid #34d399;">
            <div style="font-size:11px; color:rgba(255,255,255,0.4); margin-bottom:4px;">CONFIDENCE PROJECTION</div>
            <div style="font-size:24px; font-weight:800; color:#34d399;">${assessment.confidence_projection_score}/10</div>
        </div>`:''}
    </div>`;

    if (assessment.overall_assessment)          html += sectionBlock('📊','Overall Body Language', assessment.overall_assessment, '#38bdf8');
    if (assessment.eye_contact_analysis)        html += sectionBlock('👁️',`Eye Contact — ${assessment.eye_contact_analysis.rating}`, assessment.eye_contact_analysis.analysis, assessment.eye_contact_analysis.rating==='Strong'?'#34d399':assessment.eye_contact_analysis.rating==='Moderate'?'#fbbf24':'#f87171');
    if (assessment.posture_analysis)            html += sectionBlock('🧍',`Posture — ${assessment.posture_analysis.rating}`, assessment.posture_analysis.analysis, assessment.posture_analysis.rating==='Good'?'#34d399':assessment.posture_analysis.rating==='Moderate'?'#fbbf24':'#f87171');
    if (assessment.strengths?.length)           html += sectionBlock('✅','Body Language Strengths',     warmBulletList(assessment.strengths),                  '#34d399');
    if (assessment.areas_for_improvement?.length) html += sectionBlock('⚠️','Areas for Improvement',   warmBulletList(assessment.areas_for_improvement),        '#f87171');
    if (assessment.improvement_recommendations?.length) html += sectionBlock('📈','Recommendations',   warmBulletList(assessment.improvement_recommendations), '#fb923c');

    document.getElementById('videoAnalysisBox').style.display    = 'block';
    document.getElementById('videoAnalysisContent').innerHTML    = html;
}

// ═══════════════════════════════════════════════════════════════════
// COMPLETE — save data & redirect to report page
// ═══════════════════════════════════════════════════════════════════
async function completeInterview() {
    if (isCompleting) return;
    isCompleting = true;
    interviewActive = false;
    statusText.innerText   = 'Interview completed!';
    questionText.innerText = 'Thank you for completing the interview!';
    answerText.innerText   = '';
    setPill('done', 'DONE');

    if (startBtn) startBtn.disabled = true;
    if (skipBtn)  skipBtn.disabled  = true;
    if (stopBtn)  stopBtn.disabled  = true;
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }

    if (pendingAnalyses.size > 0) {
        statusText.innerText = `Finishing ${pendingAnalyses.size} answer analysis request(s)…`;
        await Promise.allSettled([...pendingAnalyses]);
    }

    // ── Persist all answer data for report.html ──
    sessionStorage.setItem('interviewAnswers', JSON.stringify(answers));
    sessionStorage.setItem('totalQuestions',   String(TOTAL_QUESTIONS));

    // ── Short delay, then navigate to report page ──
    statusText.innerText = 'Interview complete! Generating your report…';
    setTimeout(() => {
        window.location.href = 'report.html';
    }, 1800);
}

function resetInterview() {
    interviewActive = false;
    if (startBtn) startBtn.disabled = false;
    if (skipBtn)  skipBtn.disabled  = true;
    if (stopBtn)  stopBtn.disabled  = true;
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        if (stream) stream.getTracks().forEach(t => t.stop());
    }
    if (videoRecorder && videoRecorder.state === 'recording') videoRecorder.stop();
    window.speechSynthesis.cancel();
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
}

document.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && mediaRecorder && mediaRecorder.state === 'recording') {
        e.preventDefault(); stopRecording();
    }
    if (e.code === 'Escape' && interviewActive) {
        e.preventDefault(); stopInterview();
    }
});

// ═══════════════════════════════════════════════════════════════════
// SECURITY — Tab / Window Visibility Guard
// 3 warnings shown on violations 1, 2, 3 — interview auto-ends on 4th
// ═══════════════════════════════════════════════════════════════════

let tabViolationCount = 0;
const MAX_WARNINGS    = 3;   // warnings shown before termination
let   lastBlurTime    = 0;   // debounce blur + visibilitychange firing together

/** Build the dot indicators row (e.g. ● ● ○ ○) */
function buildViolationDots(current, max) {
    return Array.from({ length: max }, (_, i) => {
        const filled = i < current;
        return `<div style="
            width:12px; height:12px; border-radius:50%;
            background:${filled ? '#f87171' : 'rgba(248,113,113,0.15)'};
            border:1.5px solid ${filled ? '#f87171' : 'rgba(248,113,113,0.35)'};
            ${filled ? 'box-shadow:0 0 6px rgba(248,113,113,0.5);' : ''}
            transition:all .3s;
        "></div>`;
    }).join('');
}

/** Show a full-screen overlay warning */
function showTabWarningOverlay(isFinal) {
    const existing = document.getElementById('tabSecurityOverlay');
    if (existing) existing.remove();

    const warningsLeft = MAX_WARNINGS - tabViolationCount;
    const overlay = document.createElement('div');
    overlay.id = 'tabSecurityOverlay';
    overlay.style.cssText = `
        position: fixed; inset: 0; z-index: 99999;
        background: rgba(0,0,0,0.94);
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
        gap: 18px; padding: 40px;
        font-family: 'Inter', sans-serif;
        animation: fadeInOverlay .2s ease;
    `;

    // Countdown bar only on warnings (not final)
    const countdownBar = !isFinal ? `
        <div style="width:320px; height:3px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden; margin-top:4px;">
            <div id="overlayCountdown" style="height:100%; width:100%; background:#f87171; border-radius:3px;
                 transition:width 3s linear;"></div>
        </div>` : '';

    overlay.innerHTML = `
        <style>
            @keyframes fadeInOverlay { from{opacity:0;transform:scale(1.04)} to{opacity:1;transform:scale(1)} }
            @keyframes pulseIcon     { 0%,100%{transform:scale(1)} 50%{transform:scale(1.1)} }
            @keyframes shakeOverlay  { 0%,100%{transform:translateX(0)} 20%,60%{transform:translateX(-8px)} 40%,80%{transform:translateX(8px)} }
        </style>

        <!-- Icon -->
        <div style="
            width:80px; height:80px; border-radius:50%;
            background:rgba(248,113,113,0.1);
            border:2px solid rgba(248,113,113,${isFinal ? '0.9' : '0.6'});
            display:flex; align-items:center; justify-content:center;
            font-size:36px;
            animation:${isFinal ? 'shakeOverlay .4s ease, pulseIcon 1s ease-in-out 0.4s infinite' : 'pulseIcon 1.4s ease-in-out infinite'};">
            ${isFinal ? '🚫' : '⚠️'}
        </div>

        <!-- Title -->
        <h2 style="color:#f87171; font-size:22px; font-weight:800; margin:0; text-align:center; letter-spacing:-.3px;">
            ${isFinal ? 'Interview Terminated' : 'Tab Switch Detected'}
        </h2>

        <!-- Body text -->
        <p style="color:rgba(255,255,255,0.6); font-size:14px; text-align:center; max-width:380px; line-height:1.7; margin:0;">
            ${isFinal
                ? `You switched tabs or windows <strong style="color:#f87171;">4 times</strong>. Your interview has been automatically ended and flagged.`
                : `Switching tabs or windows is <strong style="color:#fff;">not allowed</strong> during the interview. Stay on this page at all times.`
            }
        </p>

        <!-- Violation dot counter -->
        <div style="display:flex; align-items:center; gap:8px; margin-top:2px;">
            <span style="font-size:11px; letter-spacing:1px; color:rgba(255,255,255,0.3); font-family:'IBM Plex Mono',monospace;">VIOLATIONS</span>
            <div style="display:flex; gap:6px; align-items:center;">
                ${buildViolationDots(tabViolationCount, MAX_WARNINGS + 1)}
            </div>
        </div>

        <!-- Warning count badge OR terminated badge -->
        ${isFinal
            ? `<div style="padding:10px 28px; border-radius:8px;
                           background:rgba(248,113,113,0.15); border:1px solid rgba(248,113,113,0.4);
                           color:#fca5a5; font-size:13px; letter-spacing:.8px; font-weight:600;">
                   INTERVIEW ENDED · Redirecting to report…
               </div>`
            : `<div style="display:flex; flex-direction:column; align-items:center; gap:6px;">
                   <div style="padding:8px 22px; border-radius:8px;
                               background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.3);
                               color:#fbbf24; font-size:13px; letter-spacing:.5px; font-weight:600;">
                       ⚠️ Warning ${tabViolationCount} of ${MAX_WARNINGS} — ${warningsLeft} remaining before termination
                   </div>
                   <span style="font-size:11px; color:rgba(255,255,255,0.25);">Returning to interview automatically…</span>
               </div>`
        }

        ${countdownBar}
    `;

    document.body.appendChild(overlay);

    if (!isFinal) {
        // Shrink countdown bar
        requestAnimationFrame(() => {
            const bar = document.getElementById('overlayCountdown');
            if (bar) bar.style.width = '0%';
        });
        // Auto-dismiss after 3 s
        setTimeout(() => {
            overlay.style.opacity    = '0';
            overlay.style.transition = 'opacity .35s ease';
            setTimeout(() => overlay.remove(), 350);
        }, 3000);
    }
    // Final overlay stays until redirect
}

/** Core handler — fires every time the page becomes hidden */
function handleVisibilityChange() {
    if (!interviewActive) return;
    if (document.visibilityState !== 'hidden') return;

    // Debounce: visibilitychange + blur can both fire within ms of each other
    const now = Date.now();
    if (now - lastBlurTime < 200) return;
    lastBlurTime = now;

    tabViolationCount++;

    if (tabViolationCount > MAX_WARNINGS) {
        // 4th violation — terminate
        showTabWarningOverlay(true);
        terminateForTabSwitch();
    } else {
        // Warnings 1, 2, 3
        showTabWarningOverlay(false);
    }
}

/** Hard-stop the interview due to a security violation */
function terminateForTabSwitch() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        clearTimeout(recordingTimeout);
        mediaRecorder.stop();
    }
    if (videoRecorder && videoRecorder.state === 'recording') videoRecorder.stop();
    window.speechSynthesis.cancel();
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }

    interviewActive = false;

    setPill('danger', 'TERMINATED');
    if (statusText)   statusText.innerText  = '⛔ Interview terminated — repeated tab switching detected.';
    if (questionText) questionText.innerText = 'Your interview was ended due to a security violation (4 tab switches).';
    if (answerText)   answerText.innerText   = '';
    if (indicator)    indicator.classList.remove('recording');

    if (startBtn) startBtn.disabled = true;
    if (skipBtn)  skipBtn.disabled  = true;
    if (stopBtn)  stopBtn.disabled  = true;

    try {
        sessionStorage.setItem('interviewTerminatedReason', 'tab_switch_x4');
        sessionStorage.setItem('interviewAnswers',          JSON.stringify(answers));
        sessionStorage.setItem('totalQuestions',            String(TOTAL_QUESTIONS));
        sessionStorage.setItem('tabViolations',             String(tabViolationCount));
    } catch (_) {}

    setTimeout(() => { window.location.href = 'report.html'; }, 4500);
}

/** Catch window blur (Alt+Tab to desktop app) without double-counting */
function handleWindowBlur() {
    if (!interviewActive) return;
    if (document.visibilityState === 'visible') {
        const now = Date.now();
        if (now - lastBlurTime < 200) return;
        lastBlurTime = now;

        tabViolationCount++;
        if (tabViolationCount > MAX_WARNINGS) {
            showTabWarningOverlay(true);
            terminateForTabSwitch();
        } else {
            showTabWarningOverlay(false);
        }
    }
}

// Register the security listeners
document.addEventListener('visibilitychange', handleVisibilityChange);
window.addEventListener('blur', handleWindowBlur);
