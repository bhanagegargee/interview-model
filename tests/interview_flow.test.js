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
        skipBtn = document.getElementById('skipBtn');
        stopBtn = document.getElementById('stopBtn');
        interviewActive = true;
        speakQuestion = async () => {};
        startRecording = async () => {
            mediaRecorder = makeRecorder();
            videoRecorder = makeRecorder();
            audioChunks = [new Uint8Array([1, 2, 3])];
            videoChunks = [new Uint8Array([4, 5, 6])];
        };
    `, context);

    const flush = () => new Promise((resolve) => setImmediate(resolve));
    await vm.runInContext('askNextQuestion()', context);
    assert.equal(element('questionText').innerText, 'Question one?');
    assert.equal(vm.runInContext('TOTAL_QUESTIONS', context), 3);

    for (const nextQuestion of ['Question two?', 'Question three?']) {
        vm.runInContext('stopRecording()', context);
        await flush();
        assert.equal(element('questionText').innerText, nextQuestion);
        assert.equal(stored.interviewAnswers, undefined);
    }

    vm.runInContext('stopRecording()', context);
    await flush();
    assert.equal(requests.size, 3);
    assert.equal(stored.interviewAnswers, undefined);
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
