// Clinical Scenarios
const scenarios = {
    cardiac: {
        text: "Patient presents with severe crushing chest pain radiating to left arm, diaphoresis, and shortness of breath. Patient appears pale and distressed. Onset 30 minutes ago.",
        patientId: "P-101",
        expectedLevel: "RED"
    },
    respiratory: {
        text: "Patient reports high fever (103°F), productive cough, and difficulty breathing for 3 days. SpO2 measured at 94%. No chest pain. General fatigue reported.",
        patientId: "P-999",
        expectedLevel: "YELLOW"
    },
    dermatology: {
        text: "Patient presents with localized itchy rash on forearm, appeared after gardening. No fever, no respiratory symptoms, no systemic involvement.",
        patientId: "P-102",
        expectedLevel: "GREEN"
    }
};

// Triage Protocols
const protocols = {
    RED: {
        title: "Red Protocol - Emergency",
        text: "Chest pain with diaphoresis or radiating arm pain indicates potential cardiac emergency.",
        criteria: ["Chest pain present", "Diaphoresis (sweating)", "Radiating pain to arm", "Patient distress"]
    },
    YELLOW: {
        title: "Yellow Protocol - Urgent",
        text: "Fever with respiratory symptoms and reduced oxygen saturation requires urgent evaluation.",
        criteria: ["Elevated temperature (>101°F)", "Respiratory symptoms", "SpO2 below 95%", "No cardiac indicators"]
    },
    GREEN: {
        title: "Green Protocol - Routine",
        text: "Localized dermatological symptoms without systemic involvement - standard outpatient care.",
        criteria: ["Localized symptoms", "No fever", "No respiratory involvement", "No systemic symptoms"]
    }
};

// Patient Database with treatment considerations
const patients = {
    "P-101": { 
        name: "Sarah Connor", 
        age: 45, 
        history: "Hypertension, Penicillin Allergy",
        treatmentConsiderations: [
            "ALLERGY: Avoid Penicillin, Amoxicillin, Ampicillin",
            "Use Azithromycin or Fluoroquinolones instead",
            "Monitor blood pressure closely",
            "Caution with NSAIDs and decongestants"
        ]
    },
    "P-102": { 
        name: "Logan Roy", 
        age: 82, 
        history: "Previous Stroke, Diabetes Type 2",
        treatmentConsiderations: [
            "HIGH RISK: Previous stroke - rapid neuro assessment",
            "Monitor blood glucose levels",
            "Caution with corticosteroids",
            "Neurological status monitoring required"
        ]
    },
    "P-999": { 
        name: "John Doe", 
        age: 25, 
        history: "None",
        treatmentConsiderations: [
            "No significant medical history",
            "Standard treatment protocols apply"
        ]
    }
};

// DOM Elements
const scenarioSelect = document.getElementById('scenario-select');
const symptomsText = document.getElementById('symptoms-text');
const analyzeBtn = document.getElementById('analyze-btn');
const logContainer = document.getElementById('log-container');
const logCount = document.getElementById('log-count');
const resultProtocol = document.getElementById('result-protocol');
const resultDecision = document.getElementById('result-decision');
const decisionLevel = document.getElementById('decision-level');
const decisionAction = document.getElementById('decision-action');

// Architecture Elements
const blocks = {
    input: document.getElementById('block-input'),
    orchestrator: document.getElementById('block-orchestrator'),
    nodeContext: document.getElementById('block-node-context'),
    nodeMedical: document.getElementById('block-node-medical'),
    nodeRouter: document.getElementById('block-node-router'),
    toolPatient: document.getElementById('block-tool-patient'),
    toolTreatment: document.getElementById('block-tool-treatment'),
    toolGuidelines: document.getElementById('block-tool-guidelines'),
    dbPatient: document.getElementById('block-db-patient'),
    dbTreatment: document.getElementById('block-db-treatment'),
    dbGuidelines: document.getElementById('block-db-guidelines'),
    actionRed: document.getElementById('block-action-red'),
    actionYellow: document.getElementById('block-action-yellow'),
    actionGreen: document.getElementById('block-action-green')
};

const statuses = {
    input: document.getElementById('status-input'),
    orchestrator: document.getElementById('status-orchestrator'),
    nodeContext: document.getElementById('status-node-context'),
    nodeMedical: document.getElementById('status-node-medical'),
    nodeRouter: document.getElementById('status-node-router'),
    toolPatient: document.getElementById('status-tool-patient'),
    toolTreatment: document.getElementById('status-tool-treatment'),
    toolGuidelines: document.getElementById('status-tool-guidelines')
};

const calls = {
    patientRecord: document.getElementById('call-patient-record'),
    treatment: document.getElementById('call-treatment'),
    guidelines: document.getElementById('call-guidelines')
};

const agents = {
    nurse: document.getElementById('agent-nurse'),
    doctor: document.getElementById('agent-doctor')
};

const agentArrow = document.querySelector('.agent-arrow');
const flowArrows = document.querySelectorAll('.flow-arrow');
const toolGroups = document.querySelectorAll('.tool-group');

// State
let logEntries = 0;
let startTime = null;

// Utilities
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function getTimestamp() {
    if (!startTime) return '0.00s';
    return ((Date.now() - startTime) / 1000).toFixed(2) + 's';
}

// Update patient display
function updatePatientDisplay(patientId) {
    const patient = patients[patientId];
    document.getElementById('display-patient-id').textContent = patientId;
    document.getElementById('display-patient-name').textContent = patient.name;
    document.getElementById('display-patient-history').textContent = patient.history;
}

// Update scenario
function updateScenario() {
    const scenario = scenarios[scenarioSelect.value];
    symptomsText.textContent = scenario.text;
    updatePatientDisplay(scenario.patientId);
    resetAll();
}

// Reset everything
function resetAll() {
    // Reset blocks
    Object.values(blocks).forEach(block => block?.classList.remove('active'));
    
    // Reset statuses
    Object.entries(statuses).forEach(([key, el]) => {
        if (el) {
            if (key === 'input') el.textContent = 'Waiting';
            else if (key === 'orchestrator') el.textContent = 'Idle';
            else if (key.startsWith('node')) el.textContent = 'Pending';
            else if (key.startsWith('tool')) el.textContent = 'Ready';
        }
    });
    
    // Reset tool calls
    Object.values(calls).forEach(call => call?.classList.remove('active'));
    
    // Reset agents
    Object.values(agents).forEach(agent => agent?.classList.remove('active'));
    agentArrow?.classList.remove('active');
    
    // Reset flow arrows
    flowArrows.forEach(arrow => arrow.classList.remove('active'));
    
    // Reset tool groups
    toolGroups.forEach(group => group.classList.remove('active'));
    
    // Reset logs
    logContainer.innerHTML = '<div class="log-empty">Execution trace will appear here when analysis runs.</div>';
    logEntries = 0;
    logCount.textContent = '0 events';
    
    // Reset results
    resultProtocol.innerHTML = '<div class="protocol-empty">Protocol match will display after analysis.</div>';
    resultDecision.className = 'result-decision';
    decisionLevel.textContent = 'STANDBY';
    decisionAction.textContent = 'Awaiting analysis...';
}

// Add log entry
function addLog(type, source, message) {
    if (logContainer.querySelector('.log-empty')) {
        logContainer.innerHTML = '';
    }
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `
        <span class="log-time">${getTimestamp()}</span>
        <span class="log-source">${source}</span>
        <span class="log-message">${message}</span>
    `;
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
    
    logEntries++;
    logCount.textContent = `${logEntries} events`;
}

// Display protocol with treatment considerations
function displayProtocol(level, patient) {
    const protocol = protocols[level];
    const colorClass = level.toLowerCase();
    
    resultProtocol.innerHTML = `
        <div class="protocol-card ${colorClass}">
            <div class="protocol-title">${protocol.title}</div>
            <p class="protocol-text">${protocol.text}</p>
            <div class="protocol-criteria">
                <div class="criteria-label">Matched Criteria</div>
                ${protocol.criteria.map(c => `
                    <div class="criteria-item">
                        <span class="criteria-check">✓</span>
                        <span>${c}</span>
                    </div>
                `).join('')}
            </div>
        </div>
        <div class="treatment-card">
            <div class="treatment-title">Treatment Considerations (from Patient History)</div>
            ${patient.treatmentConsiderations.map(c => `
                <div class="treatment-item">
                    <span class="treatment-bullet">•</span>
                    <span>${c}</span>
                </div>
            `).join('')}
        </div>
    `;
}

// Display final decision
function displayDecision(level, plan) {
    resultDecision.className = `result-decision status-${level.toLowerCase()}`;
    
    const levelText = {
        RED: 'CRITICAL (RED)',
        YELLOW: 'URGENT (YELLOW)',
        GREEN: 'ROUTINE (GREEN)'
    };
    
    decisionLevel.textContent = levelText[level] || level;
    decisionAction.innerHTML = plan.replace(/\n/g, '<br>');
}

// Animate architecture flow
async function animateFlow(level, scenario) {
    const patient = patients[scenario.patientId];
    
    // === STEP 1: Input received ===
    blocks.input?.classList.add('active');
    statuses.input.textContent = 'Received';
    addLog('data', 'Input', `Patient ${scenario.patientId} data received`);
    await sleep(300);
    
    flowArrows[0]?.classList.add('active');
    await sleep(200);
    
    // === STEP 2: Orchestrator starts ===
    blocks.orchestrator?.classList.add('active');
    statuses.orchestrator.textContent = 'Running';
    addLog('orchestrator', 'LangGraph', 'Workflow engine started, initializing state');
    await sleep(300);
    
    flowArrows[1]?.classList.add('active');
    await sleep(200);
    
    // === STEP 3: Node 1 - gather_context ===
    blocks.nodeContext?.classList.add('active');
    statuses.nodeContext.textContent = 'Executing';
    addLog('node', 'gather_context', 'Executing node: Gathering patient context');
    await sleep(300);
    
    // Tool call: get_patient_record
    calls.patientRecord?.classList.add('active');
    blocks.toolPatient?.classList.add('active');
    toolGroups[0]?.classList.add('active');
    statuses.toolPatient.textContent = 'Querying';
    addLog('tool', 'get_patient_record', `Querying EMR for patient ${scenario.patientId}`);
    await sleep(300);
    
    blocks.dbPatient?.classList.add('active');
    addLog('data', 'Patient EMR', `Retrieved: ${patient.name}, History: ${patient.history}`);
    statuses.toolPatient.textContent = 'Done';
    await sleep(250);
    
    // Tool call: get_treatment_considerations
    calls.treatment?.classList.add('active');
    blocks.toolTreatment?.classList.add('active');
    toolGroups[1]?.classList.add('active');
    statuses.toolTreatment.textContent = 'Analyzing';
    addLog('tool', 'get_treatment', `Analyzing history for contraindications`);
    await sleep(300);
    
    blocks.dbTreatment?.classList.add('active');
    addLog('data', 'Treatment Rules', `Found ${patient.treatmentConsiderations.length} considerations`);
    statuses.toolTreatment.textContent = 'Done';
    await sleep(250);
    
    statuses.nodeContext.textContent = 'Complete';
    addLog('node', 'gather_context', 'Node complete: Context stored in state');
    await sleep(200);
    
    flowArrows[2]?.classList.add('active');
    await sleep(200);
    
    // === STEP 4: Node 2 - medical_board ===
    blocks.nodeMedical?.classList.add('active');
    statuses.nodeMedical.textContent = 'Executing';
    addLog('node', 'medical_board', 'Executing node: Running CrewAI medical analysis');
    await sleep(300);
    
    // Agent: Triage Nurse
    agents.nurse?.classList.add('active');
    addLog('agent', 'Triage Nurse', 'Agent activated: Analyzing symptoms');
    await sleep(400);
    
    // Tool call: get_triage_guidelines
    calls.guidelines?.classList.add('active');
    blocks.toolGuidelines?.classList.add('active');
    toolGroups[2]?.classList.add('active');
    statuses.toolGuidelines.textContent = 'Searching';
    addLog('tool', 'get_triage_guidelines', 'Searching protocols for symptom match');
    await sleep(300);
    
    blocks.dbGuidelines?.classList.add('active');
    addLog('data', 'Triage Protocols', `Matched: ${level} PROTOCOL`);
    statuses.toolGuidelines.textContent = 'Done';
    await sleep(250);
    
    addLog('agent', 'Triage Nurse', `Findings: Protocol indicates ${level} level`);
    await sleep(200);
    
    // Agent: ER Physician
    agentArrow?.classList.add('active');
    await sleep(150);
    
    agents.doctor?.classList.add('active');
    addLog('agent', 'ER Physician', 'Agent activated: Reviewing findings');
    await sleep(400);
    
    addLog('agent', 'ER Physician', `Decision: Confirmed ${level} based on protocol`);
    await sleep(200);
    
    statuses.nodeMedical.textContent = 'Complete';
    addLog('node', 'medical_board', `Node complete: Diagnosis = ${level}`);
    
    // Display protocol
    displayProtocol(level, patient);
    await sleep(200);
    
    flowArrows[3]?.classList.add('active');
    await sleep(200);
    
    // === STEP 5: Router ===
    blocks.nodeRouter?.classList.add('active');
    statuses.nodeRouter.textContent = 'Routing';
    addLog('node', 'route_logic', `Evaluating state.final_diagnosis = "${level}"`);
    await sleep(300);
    
    const routeTarget = level.toLowerCase();
    statuses.nodeRouter.textContent = `→ ${routeTarget}`;
    addLog('node', 'route_logic', `Routing to action node: "${routeTarget}"`);
    await sleep(200);
    
    // === STEP 6: Action Node ===
    const actionBlock = blocks[`action${level.charAt(0) + level.slice(1).toLowerCase()}`];
    actionBlock?.classList.add('active');
    addLog('decision', routeTarget, `Generating action plan with treatment considerations`);
    await sleep(300);
    
    addLog('decision', 'Output', `Triage complete: ${level} with treatment notes applied`);
}

// Run analysis
async function runAnalysis() {
    const scenario = scenarios[scenarioSelect.value];
    
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Running Analysis...';
    
    resetAll();
    startTime = Date.now();
    decisionLevel.textContent = 'ANALYZING...';
    decisionAction.textContent = 'Processing through workflow...';
    
    try {
        const response = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                patient_id: scenario.patientId,
                symptoms: scenario.text
            })
        });
        
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        
        const data = await response.json();
        
        const diagText = data.diagnosis.toUpperCase();
        let level = 'GREEN';
        if (diagText.includes('RED')) level = 'RED';
        else if (diagText.includes('YELLOW')) level = 'YELLOW';
        
        await animateFlow(level, scenario);
        displayDecision(level, data.plan);
        
    } catch (error) {
        console.error('Analysis error:', error);
        addLog('decision', 'Error', error.message);
        decisionLevel.textContent = 'ERROR';
        decisionAction.textContent = `Analysis failed: ${error.message}`;
        resultDecision.className = 'result-decision status-red';
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Run Triage Analysis';
    }
}

// Event Listeners
scenarioSelect.addEventListener('change', updateScenario);
analyzeBtn.addEventListener('click', runAnalysis);

// Initialize
updateScenario();
