const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('advances through three cached questions before analysis finishes, then waits for the report', async () => {
    const stored = {
        candidateEmail: 'candidate@example.test',
        candidateName: 'Candidate',
        generatedQuestions: JSON.stringify(['Question one?', 'Question two?', 'Question three?']),
        generatedTimings: JSON.stringify([60000, 75000, 90000])
    };
    const requests = new Map();
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) {
            elements.set(id, {
                innerText: '', textContent: '', style: {}, classList: { add() {}, remove() {} }
            });
        }
        return elements.get(id);
    };
    const context = vm.createContext({
        Blob, FormData, URL, Uint8Array, console, queueMicrotask,
        clearTimeout() {},
        setTimeout(callback, ms) {
            if (ms !== 1800) queueMicrotask(callback);
            return 1;
        },
        sessionStorage: {
            getItem(key) { return stored[key] ?? null; },
            setItem(key, value) { stored[key] = value; }
        },
        document: {
            addEventListener() {},
            getElementById: element,
            querySelector() { return null; }
        },
        window: { addEventListener() {}, speechSynthesis: { cancel() {} } },
        fetch(url, options) {
            assert.match(url, /\/analyze-answer$/);
            const index = Number(options.body.get('question_number'));
            return new Promise((resolve) => requests.set(index, resolve));
        },
        makeRecorder() {
            const listeners = [];
            return {
                state: 'recording',
                addEventListener(name, listener) {
                    if (name === 'stop') listeners.push(listener);
                },
                stop() {
                    this.state = 'inactive';
                    queueMicrotask(() => listeners.forEach((listener) => listener()));
                }
            };
        }
    });
    const script = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8');
    vm.runInContext(script, context);
    vm.runInContext(`
        statusText = document.getElementById('statusText');
        questionText = document.getElementById('questionText');
        answerText = document.getElementById('answerText');
        progressText = document.getElementById('progressText');
        indicator = document.getElementById('indicator');
        startBtn = document.getElementById('startBtn');
        nextBtn = document.getElementById('nextBtn');
        stopBtn = document.getElementById('stopBtn');
        interviewActive = true;
        speakQuestion = async () => {};
        startRecording = async () => {
            mediaRecorder = makeRecorder();
            videoRecorder = makeRecorder();
            audioChunks = [new Uint8Array([1, 2, 3])];
            videoChunks = [new Uint8Array([4, 5, 6])];
            nextBtn.disabled = false;
        };
    `, context);

    const flush = () => new Promise((resolve) => setImmediate(resolve));
    await vm.runInContext('askNextQuestion()', context);
    assert.equal(element('questionText').innerText, 'Question one?');
    assert.equal(vm.runInContext('TOTAL_QUESTIONS', context), 3);

    const expectedQuestions = ['Question one?', 'Question two?', 'Question three?'];
    for (let index = 0; index < expectedQuestions.length - 1; index++) {
        if (index === 0) {
            await vm.runInContext('nextQuestion()', context); // clicking Next ends recording and advances once saved
            await flush();
            assert.equal(element('questionText').innerText, expectedQuestions[index + 1]);
            assert.equal(requests.size, 1);
            continue;
        }
        vm.runInContext('stopRecording()', context);
        await flush();
        assert.equal(element('questionText').innerText, expectedQuestions[index]);
        assert.equal(element('nextBtn').disabled, false);
        assert.match(element('statusText').innerText, /Click Next/);
        assert.equal(stored.interviewAnswers, undefined);
        await vm.runInContext('nextQuestion()', context);
        await flush();
        assert.equal(element('questionText').innerText, expectedQuestions[index + 1]);
    }

    vm.runInContext('stopRecording()', context);
    await flush();
    assert.equal(requests.size, 3);
    assert.equal(stored.interviewAnswers, undefined);
    assert.equal(element('questionText').innerText, 'Question three?');
    assert.equal(element('nextBtn').disabled, false);
    await vm.runInContext('nextQuestion()', context);
    await flush();
    assert.match(element('statusText').innerText, /Finishing 3 answer analysis/);

    for (const index of [2, 0, 1]) {
        requests.get(index)({
            ok: true,
            json: async () => ({ transcript: `Answer ${index + 1}`, ai_score: { scoring_method: 'ai' } })
        });
        await flush();
    }

    const answers = JSON.parse(stored.interviewAnswers);
    assert.deepEqual(answers.map((answer) => answer.answer), ['Answer 1', 'Answer 2', 'Answer 3']);
    assert.equal(stored.totalQuestions, '3');
});

test('requires consecutive multiple-face results and terminates once without submitting the active recording', () => {
    const stored = {};
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, {
            innerText: '', textContent: '', style: {}, srcObject: null,
            classList: { add() {}, remove() {} }
        });
        return elements.get(id);
    };
    const stopCounts = { audio: 0, video: 0 };
    const makeRecorder = (key) => ({ state: 'recording', stop() { stopCounts[key]++; this.state = 'inactive'; } });
    const context = vm.createContext({
        Blob, FormData, URL, Uint8Array, console, clearTimeout() {}, setTimeout() { return 1; },
        sessionStorage: {
            getItem(key) { return stored[key] ?? null; },
            setItem(key, value) { stored[key] = value; }
        },
        document: { addEventListener() {}, getElementById: element, querySelector() {} },
        window: { addEventListener() {}, speechSynthesis: { cancel() {} } }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    context.makeRecorderForTest = (key) => makeRecorder(key);
    vm.runInContext(`
        interviewActive = true;
        isDetectingFaces = true;
        answers = [{ question: 'Earlier?', answer: 'Saved' }];
        mediaRecorder = makeRecorderForTest('audio');
        videoRecorder = makeRecorderForTest('video');
        startBtn = document.getElementById('startBtn');
        nextBtn = document.getElementById('nextBtn');
        stopBtn = document.getElementById('stopBtn');
        statusText = document.getElementById('statusText');
        questionText = document.getElementById('questionText');
        answerText = document.getElementById('answerText');
        indicator = document.getElementById('indicator');
    `, context);

    vm.runInContext('onFaceResults({ multiFaceLandmarks: [{}, {}] })', context);
    assert.equal(vm.runInContext('interviewTerminated', context), false);
    vm.runInContext('onFaceResults({ multiFaceLandmarks: [[]] })', context); // one face resets
    vm.runInContext('onFaceResults({ multiFaceLandmarks: [{}, {}] })', context);
    vm.runInContext('onFaceResults({ multiFaceLandmarks: [{}, {}] })', context);
    vm.runInContext('onFaceResults({ multiFaceLandmarks: [{}, {}] })', context); // duplicate callback is idempotent

    assert.equal(vm.runInContext('interviewTerminated', context), true);
    assert.deepEqual(stopCounts, { audio: 1, video: 1 });
    assert.equal(stored.interviewTerminatedReason, 'multiple_people');
    assert.deepEqual(JSON.parse(stored.interviewAnswers), [{ question: 'Earlier?', answer: 'Saved' }]);
    assert.equal(element('multiplePeopleTermination').style.display, 'flex');
    vm.runInContext('sendMediaToBackend(1, "Active question")', context);
    assert.equal(vm.runInContext('answers.length', context), 1);
});

test('face warnings count distinct visibility episodes and terminate on the second', () => {
    const stored = {};
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, { innerText: '', textContent: '', style: {}, classList: { add() {}, remove() {} } });
        return elements.get(id);
    };
    const context = vm.createContext({
        Blob, FormData, URL, Uint8Array, console, clearTimeout() {}, setTimeout() { return 1; },
        sessionStorage: { getItem(key) { return stored[key] ?? null; }, setItem(key, value) { stored[key] = value; } },
        document: { addEventListener() {}, getElementById: element, querySelector() {} },
        window: { addEventListener() {}, speechSynthesis: { cancel() {} } }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    vm.runInContext(`
        interviewActive = true;
        startBtn = document.getElementById('startBtn'); nextBtn = document.getElementById('nextBtn');
        stopBtn = document.getElementById('stopBtn'); statusText = document.getElementById('statusText');
        questionText = document.getElementById('questionText'); answerText = document.getElementById('answerText');
        indicator = document.getElementById('indicator');
    `, context);
    const landmarks = Array.from({ length: 468 }, () => ({ x: 0.5, y: 0.5 }));
    landmarks[1] = { x: 0.5, y: 0.52 };
    landmarks[13] = { x: 0.5, y: 0.68 }; landmarks[14] = { x: 0.5, y: 0.69 };
    landmarks[33] = { x: 0.4, y: 0.4 }; landmarks[263] = { x: 0.6, y: 0.4 };
    landmarks[234] = { x: 0.3, y: 0.5 }; landmarks[454] = { x: 0.7, y: 0.5 };
    landmarks[152] = { x: 0.5, y: 0.72 };
    const cropped = landmarks.map(point => ({ ...point }));
    cropped[234] = { x: 0.005, y: 0.5 };
    context.validLandmarks = landmarks;
    context.croppedLandmarks = cropped;

    vm.runInContext('processFaceVisibility(null)', context); // missing face is handled without throwing
    vm.runInContext('processFaceVisibility(croppedLandmarks); processFaceVisibility(validLandmarks)', context);
    assert.equal(vm.runInContext('proctoringState.faceWarnings', context), 0); // isolated bad frame is smoothed
    assert.equal(vm.runInContext('faceVisibilityMetrics(validLandmarks).visible', context), true);
    for (let i = 0; i < 4; i++) vm.runInContext('processFaceVisibility(croppedLandmarks)', context);
    assert.equal(vm.runInContext('proctoringState.faceWarnings', context), 1);
    for (let i = 0; i < 10; i++) vm.runInContext('processFaceVisibility(croppedLandmarks)', context);
    assert.equal(vm.runInContext('proctoringState.faceWarnings', context), 1); // same episode
    for (let i = 0; i < 4; i++) vm.runInContext('processFaceVisibility(validLandmarks)', context);
    for (let i = 0; i < 4; i++) vm.runInContext('processFaceVisibility(croppedLandmarks)', context);
    assert.equal(vm.runInContext('interviewTerminated', context), true);
    assert.equal(stored.interviewTerminatedReason, 'face_visibility');
});

test('phone detections need confirmation, count once per episode, and use an independent warning counter', () => {
    const stored = {};
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, { innerText: '', textContent: '', style: {}, classList: { add() {}, remove() {} } });
        return elements.get(id);
    };
    const context = vm.createContext({
        Blob, FormData, URL, Uint8Array, console, clearTimeout() {}, setTimeout() { return 1; },
        sessionStorage: { getItem(key) { return stored[key] ?? null; }, setItem(key, value) { stored[key] = value; } },
        document: { addEventListener() {}, getElementById: element, querySelector() {} },
        window: { addEventListener() {}, speechSynthesis: { cancel() {} } }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    vm.runInContext(`
        interviewActive = true;
        startBtn = document.getElementById('startBtn'); nextBtn = document.getElementById('nextBtn');
        stopBtn = document.getElementById('stopBtn'); statusText = document.getElementById('statusText');
        questionText = document.getElementById('questionText'); answerText = document.getElementById('answerText');
        indicator = document.getElementById('indicator');
    `, context);
    context.lowConfidence = [{ class: 'cell phone', score: 0.4 }];
    context.phone = [{ class: 'cell phone', score: 0.9 }];
    context.otherObject = [{ class: 'book', score: 0.99 }];
    vm.runInContext('handlePhoneResults(lowConfidence); handlePhoneResults(otherObject); handlePhoneResults(phone)', context);
    assert.equal(vm.runInContext('proctoringState.phoneWarnings', context), 0); // one isolated positive
    vm.runInContext('handlePhoneResults(phone);', context);
    assert.equal(vm.runInContext('proctoringState.phoneWarnings', context), 1);
    vm.runInContext('for (let i = 0; i < 8; i++) handlePhoneResults(phone)', context);
    assert.equal(vm.runInContext('proctoringState.phoneWarnings', context), 1); // continuous phone = one episode
    vm.runInContext('for (let i = 0; i < 4; i++) handlePhoneResults([])', context);
    vm.runInContext('handlePhoneResults(phone); handlePhoneResults(phone)', context);
    assert.equal(vm.runInContext('interviewTerminated', context), true);
    assert.equal(stored.interviewTerminatedReason, 'mobile_phone');
    assert.equal(vm.runInContext('proctoringState.faceWarnings', context), 0);
});

test('live object predictions are shown as labels and drawn over the camera preview', () => {
    const elements = new Map();
    const drawnBoxes = [];
    const canvasContext = {
        clearRect() {}, strokeRect(...args) { drawnBoxes.push(args); }, fillRect() {}, fillText() {},
        measureText(text) { return { width: text.length * 8 }; }
    };
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, {
            innerText: '', textContent: '', style: {}, videoWidth: 640, videoHeight: 360,
            width: 0, height: 0, getContext() { return canvasContext; }, classList: { add() {}, remove() {} }
        });
        return elements.get(id);
    };
    const context = vm.createContext({
        Blob, FormData, URL, Uint8Array, console, clearTimeout() {}, setTimeout() { return 1; },
        sessionStorage: { getItem() { return null; }, setItem() {} },
        document: { addEventListener() {}, getElementById: element, querySelector() {} },
        window: { addEventListener() {}, speechSynthesis: { cancel() {} } }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'frontend', 'script.js'), 'utf8'), context);
    context.predictions = [
        { class: 'chair', score: 0.91, bbox: [20, 30, 120, 150] },
        { class: 'cell phone', score: 0.82, bbox: [220, 80, 40, 75] },
        { class: 'cup', score: 0.2, bbox: [300, 100, 50, 50] }
    ];
    vm.runInContext('handleObjectDetections(predictions)', context);
    assert.match(element('detectedObjects').textContent, /chair \(91%\)/);
    assert.match(element('detectedObjects').textContent, /cell phone \(82%\)/);
    assert.doesNotMatch(element('detectedObjects').textContent, /cup/);
    assert.equal(drawnBoxes.length, 2);
    assert.equal(element('objectDetectionOverlay').width, 640);
    assert.equal(element('objectDetectionOverlay').height, 360);
});
