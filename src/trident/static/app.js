'use strict';

// PEAKWHALE TRIDENT web UI.
// Everything shown here comes from the server: rule packs from /api/packs,
// decisions and the audit trail from /api/triage. The UI never invents a level.

const NODES = ['validate_input', 'screen_rules', 'classify', 'apply_rules', 'review', 'decide'];
const STEP_STATUS_TEXT = { ok: 'Done', escalated: 'Escalated', error: 'Error', skipped: 'Skipped' };
const STEP_LOG_TYPE = { ok: 'node', escalated: 'warn', error: 'error', skipped: 'data' };
const LEVEL_COLORS = ['red', 'orange', 'yellow', 'green', 'blue', 'gray'];
const STORAGE_KEY = 'trident.pack';

const $ = (id) => document.getElementById(id);

const ui = {
    packSelect: $('pack-select'),
    exampleSelect: $('example-select'),
    caseText: $('case-text'),
    analyzeBtn: $('analyze-btn'),
    logContainer: $('log-container'),
    logCount: $('log-count'),
    resultProtocol: $('result-protocol'),
    resultDecision: $('result-decision'),
    decisionLevel: $('decision-level'),
    decisionAction: $('decision-action'),
    levelBlocks: $('level-blocks'),
    disclaimerBanner: $('disclaimer-banner'),
    disclaimerText: $('disclaimer-text'),
    statusLight: $('status-light'),
    statusText: $('status-text'),
    footerVersion: $('footer-version'),
    dbPackName: $('db-pack-name'),
    qaBadge: $('qa-badge'),
    qaAgrees: $('qa-agrees'),
    qaCategory: $('qa-category'),
    qaConfidence: $('qa-confidence'),
    packId: $('display-pack-id'),
    packLevels: $('display-pack-levels'),
    packCategories: $('display-pack-categories'),
    packConfidence: $('display-pack-confidence'),
    charCount: $('char-count'),
};

const state = {
    packs: [],
    pack: null,
    logEntries: 0,
    startTime: null,
    // From /api/health. Text over this limit is not cut: the server sends it to human review.
    maxInputChars: null,
    auditLog: false,
};

// ---------- small helpers ----------

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

function levelName(id, label) {
    return id.toLowerCase() === String(label).toLowerCase() ? label : `${id} (${label})`;
}

function colorOf(color) {
    return LEVEL_COLORS.includes(color) ? color : 'gray';
}

function getTimestamp() {
    if (!state.startTime) return '0.00s';
    return ((Date.now() - state.startTime) / 1000).toFixed(2) + 's';
}

function seconds(ms) {
    return (Math.max(0, ms) / 1000).toFixed(2) + 's';
}

function savePackChoice(id) {
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) { /* storage may be blocked */ }
}

function loadPackChoice() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
}

// ---------- log ----------

// time: the time to show. Default: real time since the run started.
function addLog(type, source, message, time) {
    if (ui.logContainer.querySelector('.log-empty')) {
        ui.logContainer.replaceChildren();
    }
    const entry = make('div', `log-entry ${type}`);
    entry.append(
        make('span', 'log-time', time || getTimestamp()),
        make('span', 'log-source', source),
        make('span', 'log-message', message),
    );
    ui.logContainer.appendChild(entry);
    ui.logContainer.scrollTop = ui.logContainer.scrollHeight;
    state.logEntries += 1;
    ui.logCount.textContent = `${state.logEntries} events`;
}

function updateCharCount() {
    const length = ui.caseText.value.length;
    const limit = state.maxInputChars;
    const over = limit !== null && length > limit;
    ui.charCount.textContent = limit === null
        ? `${length} characters`
        : `${length} / ${limit} characters${over ? ' - too long, this case will go to human review' : ''}`;
    ui.charCount.classList.toggle('over', over);
}

// ---------- packs ----------

async function loadHealth() {
    try {
        const res = await fetch('/api/health');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        ui.statusText.textContent = `Server online · ${data.models.classifier}`;
        ui.statusLight.classList.remove('offline');
        ui.footerVersion.textContent = `Peakwhale™ Trident v${data.version}`;
        $('agent-classifier-model').textContent = data.models.classifier;
        $('agent-reviewer-model').textContent = data.models.reviewer;
        state.maxInputChars = Number.isInteger(data.max_input_chars) ? data.max_input_chars : null;
        state.auditLog = data.audit_log === true;
        updateCharCount();
    } catch (error) {
        ui.statusText.textContent = 'Server offline';
        ui.statusLight.classList.add('offline');
    }
}

async function loadPacks() {
    try {
        const res = await fetch('/api/packs');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        state.packs = await res.json();
    } catch (error) {
        ui.packSelect.replaceChildren(make('option', null, 'Could not load rule packs'));
        addLog('error', 'Packs', `Could not load rule packs: ${error.message}`);
        return;
    }

    ui.packSelect.replaceChildren(
        ...state.packs.map((pack) => {
            const option = make('option', null, pack.name);
            option.value = pack.id;
            return option;
        }),
    );
    ui.packSelect.disabled = false;
    ui.exampleSelect.disabled = false;
    ui.analyzeBtn.disabled = false;

    const saved = loadPackChoice();
    const first = state.packs.find((p) => p.id === saved) || state.packs.find((p) => !p.disclaimer) || state.packs[0];
    if (first) {
        ui.packSelect.value = first.id;
        selectPack(first.id);
    }
}

function selectPack(packId) {
    const pack = state.packs.find((p) => p.id === packId);
    if (!pack) return;
    state.pack = pack;
    savePackChoice(pack.id);

    ui.packId.textContent = `${pack.id} v${pack.version}`;
    ui.packLevels.textContent = pack.levels.map((l) => l.id).join(' > ');
    ui.packCategories.textContent = String(pack.categories.length);
    ui.packConfidence.textContent = pack.escalation.min_confidence.toFixed(2);
    ui.dbPackName.textContent = `${pack.id}.yaml`;

    if (pack.disclaimer) {
        ui.disclaimerText.textContent = pack.disclaimer;
        ui.disclaimerBanner.hidden = false;
    } else {
        ui.disclaimerBanner.hidden = true;
    }

    const options = pack.examples.map((example, index) => {
        const option = make('option', null, `${example.name} (expected: ${expectedText(example.expect)})`);
        option.value = String(index);
        return option;
    });
    const custom = make('option', null, 'Custom text');
    custom.value = 'custom';
    ui.exampleSelect.replaceChildren(...options, custom);
    ui.exampleSelect.value = pack.examples.length ? '0' : 'custom';
    selectExample();
    renderLevelBlocks(pack);
    resetAll();
}

function expectedText(expect) {
    if (expect.outcome === 'NEEDS_HUMAN_REVIEW') return 'human review';
    return expect.level || expect.outcome;
}

function selectExample() {
    const pack = state.pack;
    if (!pack) return;
    const value = ui.exampleSelect.value;
    if (value === 'custom') {
        ui.caseText.value = '';
        ui.caseText.focus();
    } else {
        ui.caseText.value = pack.examples[Number(value)].text;
    }
    updateCharCount();
    resetAll();
}

function renderLevelBlocks(pack) {
    const blocks = pack.levels.map((level, index) => {
        const block = make('div', `arch-block action-block level-${colorOf(level.color)}`);
        block.id = `block-level-${level.id}`;
        const tag = index === pack.levels.length - 1 ? 'Lowest' : `Level ${index + 1}`;
        block.append(
            make('div', 'block-tag action-tag', tag),
            make('div', 'block-header', `${level.id} · ${level.label}`),
            make('div', 'block-desc', level.action),
        );
        return block;
    });
    const review = make('div', 'arch-block action-block review-action');
    review.id = 'block-level-human-review';
    review.append(
        make('div', 'block-tag action-tag', 'Fail-safe'),
        make('div', 'block-header', pack.escalation.human_review.label),
        make('div', 'block-desc', pack.escalation.human_review.action),
    );
    ui.levelBlocks.replaceChildren(...blocks, review);
}

// ---------- reset ----------

function resetAll() {
    document.querySelectorAll('.arch-block, .agent-item, .call-item, .flow-arrow, .tool-group').forEach((node) => {
        node.classList.remove('active', 'interim', 'step-ok', 'step-escalated', 'step-error', 'step-skipped');
    });
    $('status-input').textContent = 'Waiting';
    $('status-orchestrator').textContent = 'Idle';
    NODES.forEach((name) => { $(`status-node-${name}`).textContent = 'Pending'; });
    ['pack', 'escalation', 'audit'].forEach((name) => { $(`status-tool-${name}`).textContent = 'Ready'; });

    ui.logContainer.replaceChildren(make('div', 'log-empty', 'Execution trace will appear here when analysis runs.'));
    state.logEntries = 0;
    ui.logCount.textContent = '0 events';

    ui.resultProtocol.replaceChildren(make('div', 'protocol-empty', 'The matched rule will display after analysis.'));
    ui.resultDecision.className = 'result-decision';
    ui.decisionLevel.textContent = 'STANDBY';
    ui.decisionAction.textContent = 'Awaiting analysis...';

    ui.qaBadge.textContent = 'Pending';
    ui.qaBadge.className = 'qa-badge';
    ui.qaAgrees.textContent = '-';
    ui.qaCategory.textContent = '-';
    ui.qaConfidence.textContent = '-';
    ui.qaConfidence.className = 'qa-value';
}

// ---------- animation from the real audit trail ----------

function activate(id, ...classes) {
    const node = $(id);
    if (node) node.classList.add('active', ...classes);
}

function activateTool(name, status) {
    activate(`group-${name}`);
    activate(`block-tool-${name}`);
    activate(`block-db-${name}`);
    $(`status-tool-${name}`).textContent = status;
}

// Replays the steps from the server's answer. The pauses are only for the
// animation: the log shows each step's real start time and duration.
async function animateSteps(result) {
    const flowArrows = document.querySelectorAll('.flow-arrow');
    const runStart = Date.parse(result.created_at);
    const at = (iso, extraMs = 0) => seconds(Date.parse(iso) - runStart + extraMs);
    activate('block-input');
    $('status-input').textContent = 'Received';
    addLog('data', 'Input', `${result.input_text.length} characters, rule pack "${result.pack}" v${result.pack_version}`, seconds(0));
    await sleep(150);
    flowArrows[0]?.classList.add('active');
    activate('block-orchestrator');
    $('status-orchestrator').textContent = 'Running';
    addLog('orchestrator', 'LangGraph', `Workflow started (request ${result.request_id.slice(0, 8)})`, seconds(0));
    await sleep(150);

    const ran = new Set();
    for (const step of result.steps) {
        ran.add(step.name);
        const index = NODES.indexOf(step.name);
        if (index > 0) flowArrows[index]?.classList.add('active');
        activate(`block-node-${step.name}`, `step-${step.status}`);
        const statusEl = $(`status-node-${step.name}`);
        if (statusEl) statusEl.textContent = `${STEP_STATUS_TEXT[step.status] || step.status} · ${step.duration_ms} ms`;

        if (step.name === 'screen_rules') {
            activate('call-escalation');
            activateTool('escalation', (step.data.matched || []).length ? 'Matched' : 'No match');
        }
        if (step.name === 'classify') {
            activate('agent-classifier');
            activate('call-schema');
        }
        if (step.name === 'apply_rules') {
            activate('call-pack');
            activateTool('pack', 'Applied');
        }
        if (step.name === 'review' && step.status !== 'skipped') activate('agent-reviewer');

        addLog(STEP_LOG_TYPE[step.status] || 'node', step.name, step.detail || STEP_STATUS_TEXT[step.status], at(step.started_at));
        for (const attempt of step.data.attempts || []) {
            const who = step.name === 'classify' ? 'Classifier' : 'Reviewer';
            const when = at(step.started_at, step.duration_ms);
            if (attempt.error) {
                addLog('warn', who, `Try ${attempt.attempt}: ${attempt.error}`, when);
            } else {
                addLog('agent', who, `Try ${attempt.attempt}: valid JSON (${attempt.ms} ms)`, when);
            }
        }
        await sleep(200);
    }

    NODES.filter((name) => !ran.has(name)).forEach((name) => {
        $(`status-node-${name}`).textContent = 'Not run';
    });

    if (state.auditLog) {
        activateTool('audit', 'Recorded');
    } else {
        // The audit trail is in the result. No JSONL file is written (TRIDENT_AUDIT_LOG is not set).
        activate('group-audit');
        activate('block-tool-audit');
        $('status-tool-audit').textContent = 'In result only';
    }
    if (result.needs_human_review) {
        activate('block-level-human-review');
        activate(`block-level-${result.level}`, 'interim');
    } else {
        activate(`block-level-${result.level}`);
    }
    activate('block-output');
    $('status-orchestrator').textContent = 'Done';
    addLog(
        result.needs_human_review ? 'warn' : 'decision',
        'Output',
        result.needs_human_review
            ? `NEEDS HUMAN REVIEW (treat as ${result.level} while waiting) · total ${result.timing_ms.total} ms`
            : `${result.level} decided · total ${result.timing_ms.total} ms`,
        seconds(result.timing_ms.total),
    );
}

// ---------- result display ----------

function displayResult(result) {
    const pack = state.packs.find((p) => p.id === result.pack) || state.pack;
    const color = result.needs_human_review ? 'review' : colorOf(result.level_color);

    // Decision
    ui.resultDecision.className = `result-decision status-${color}`;
    ui.decisionLevel.textContent = result.headline;
    const action = [make('div', 'decision-text', result.action)];
    if (result.route_to) action.push(make('div', 'decision-meta', `Route to: ${result.route_to}`));
    if (result.needs_human_review) {
        action.push(make('div', 'interim-note', `Treat as ${levelName(result.level, result.level_label)} until a person decides.`));
    }
    ui.decisionAction.replaceChildren(...action);

    // Rule matched + evidence
    const cards = [];
    const category = pack && result.category ? pack.categories.find((c) => c.id === result.category) : null;
    const card = make('div', `protocol-card ${category ? colorOf(result.rule_matched ? levelColor(pack, result.rule_matched.final_level) : 'gray') : 'review'}`);
    if (category && result.rule_matched) {
        const rm = result.rule_matched;
        card.append(make('div', 'protocol-title', `Rule: ${category.id} → ${rm.final_level}`));
        card.append(make('p', 'protocol-text', category.description));
        const criteria = make('div', 'protocol-criteria');
        criteria.append(make('div', 'criteria-label', 'Evidence from the text'));
        result.evidence.forEach((quote) => {
            const item = make('div', 'criteria-item');
            item.append(make('span', 'criteria-check', '✓'), make('span', 'evidence-quote', `"${quote}"`));
            criteria.append(item);
        });
        if (rm.raised_by && rm.raised_by.length) {
            criteria.append(make('div', 'criteria-label', `Raised from ${rm.category_level} by: ${rm.raised_by.join(', ')}`));
        }
        card.append(criteria);
    } else {
        card.append(make('div', 'protocol-title', 'No rule matched'));
        card.append(make('p', 'protocol-text', result.category === 'unknown'
            ? 'The classifier could not match the text to any category.'
            : 'The engine could not finish the checks for this case.'));
    }
    cards.push(card);

    if (result.reasons.length) {
        const reasons = make('div', 'treatment-card reasons-card');
        reasons.append(make('div', 'treatment-title', 'Why a person must review this'));
        result.reasons.forEach((reason) => {
            const item = make('div', 'treatment-item');
            item.append(make('span', 'treatment-bullet', '•'), make('span', null, reason));
            reasons.append(item);
        });
        cards.push(reasons);
    }
    if (result.escalation_rules_hit.length) {
        const hits = make('div', 'treatment-card');
        hits.append(make('div', 'treatment-title', 'Escalation rules matched'));
        result.escalation_rules_hit.forEach((hit) => {
            const item = make('div', 'treatment-item');
            item.append(make('span', 'treatment-bullet', '•'), make('span', null, `${hit.id}: ${hit.words.join(', ')}`));
            hits.append(item);
        });
        cards.push(hits);
    }
    ui.resultProtocol.replaceChildren(...cards);

    // Review (second check)
    const review = result.review;
    if (!review) {
        ui.qaBadge.textContent = 'Not run';
        ui.qaBadge.className = 'qa-badge needs-review';
        ui.qaAgrees.textContent = '-';
        ui.qaCategory.textContent = '-';
    } else {
        const agrees = review.agrees === true && review.category === result.category;
        ui.qaBadge.textContent = agrees ? 'Agrees' : 'Disagrees';
        ui.qaBadge.className = `qa-badge ${agrees ? 'validated' : 'needs-review'}`;
        ui.qaAgrees.textContent = review.agrees === true ? 'Yes' : 'No';
        ui.qaCategory.textContent = review.category;
    }
    if (typeof result.confidence === 'number') {
        const min = result.rule_matched ? result.rule_matched.min_confidence : (pack ? pack.escalation.min_confidence : 1);
        ui.qaConfidence.textContent = `${result.confidence.toFixed(2)} (min ${min.toFixed(2)})`;
        ui.qaConfidence.className = `qa-value ${result.confidence >= min ? 'high' : 'low'}`;
    }
}

function levelColor(pack, levelId) {
    const level = pack.levels.find((l) => l.id === levelId);
    return level ? colorOf(level.color) : 'gray';
}

// A failed request is shown as "needs human review". The UI never guesses a level.
function displayClientError(message) {
    ui.resultDecision.className = 'result-decision status-review';
    ui.decisionLevel.textContent = 'NEEDS HUMAN REVIEW';
    ui.decisionAction.replaceChildren(
        make('div', 'decision-text', 'The request failed, so there is no decision. A person must sort this case.'),
        make('div', 'interim-note', message),
    );
    ui.qaBadge.textContent = 'Not run';
    ui.qaBadge.className = 'qa-badge needs-review';
}

// ---------- run ----------

async function runAnalysis() {
    if (!state.pack) return;
    const text = ui.caseText.value;
    if (!text.trim()) {
        ui.caseText.focus();
        return;
    }

    ui.analyzeBtn.disabled = true;
    ui.analyzeBtn.textContent = 'Running Triage...';
    resetAll();
    state.startTime = Date.now();
    ui.decisionLevel.textContent = 'ANALYZING...';
    ui.decisionAction.textContent = 'Processing through workflow...';
    addLog('orchestrator', 'Client', `POST /api/triage (pack: ${state.pack.id})`, seconds(0));

    try {
        const res = await fetch('/api/triage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, pack: state.pack.id }),
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || {});
            throw new Error(`Server error ${res.status}: ${detail}`);
        }
        const result = await res.json();
        await animateSteps(result);
        displayResult(result);
    } catch (error) {
        console.error('Triage error:', error);
        addLog('error', 'Error', error.message);
        displayClientError(error.message);
    } finally {
        ui.analyzeBtn.disabled = false;
        ui.analyzeBtn.textContent = 'Run Triage';
    }
}

// ---------- start ----------

ui.packSelect.addEventListener('change', () => selectPack(ui.packSelect.value));
ui.exampleSelect.addEventListener('change', selectExample);
ui.caseText.addEventListener('input', () => {
    if (ui.exampleSelect.value !== 'custom') ui.exampleSelect.value = 'custom';
    updateCharCount();
});
ui.analyzeBtn.addEventListener('click', runAnalysis);

loadHealth();
loadPacks();
