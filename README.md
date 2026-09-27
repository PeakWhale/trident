<p align="center"><img src="trident.svg" width="64" height="64" alt="Trident logo"></p>

<p align="center">
  <img src="https://img.shields.io/badge/PEAKWHALE™-TRIDENT-0066cc?style=for-the-badge&labelColor=001a33" alt="PEAKWHALE™ TRIDENT" />
</p>

<h1 align="center">PEAKWHALE™ TRIDENT</h1>

<p align="center">
  <strong>AI-Powered Medical Triage System with Multi-Agent Orchestration</strong>
</p>

<p align="center">
  <a href="#architecture">Architecture</a> •
  <a href="#features">Features</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#how-it-works">How It Works</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-Orchestration-00d4aa?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph" />
  <img src="https://img.shields.io/badge/CrewAI-Multi--Agent-ff6b35?style=flat-square&logo=openai&logoColor=white" alt="CrewAI" />
  <img src="https://img.shields.io/badge/AutoGen-QA_Review-a855f7?style=flat-square&logo=microsoft&logoColor=white" alt="AutoGen" />
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Ollama-Llama_3.1-7c3aed?style=flat-square&logo=meta&logoColor=white" alt="Ollama" />
  <img src="https://img.shields.io/badge/MCP-Tools-2563eb?style=flat-square&logo=anthropic&logoColor=white" alt="MCP" />
</p>

---

## Overview

**PEAKWHALE™ TRIDENT** is an intelligent medical triage system that combines state-machine orchestration with multi-agent AI collaboration to deliver accurate, protocol-compliant emergency assessments. The system demonstrates **multi-framework orchestration** where CrewAI handles primary triage and Microsoft AutoGen provides quality assurance validation.

### Key Capabilities

- **Hybrid LLM Architecture**: LLM extracts symptom categories from natural language, protocols ensure consistent decisions
- **Protocol-Driven Decisions**: Strict adherence to clinical triage guidelines (RED/YELLOW/GREEN)
- **Patient History Integration**: Retrieves and analyzes medical history for treatment considerations
- **Contraindication Awareness**: Flags medication allergies and condition-specific cautions
- **Multi-Framework AI**: CrewAI for triage analysis + AutoGen for QA validation (two independent agent systems)
- **Transparent Reasoning**: Full audit trail of agent decisions and tool invocations

---

## Architecture

```mermaid
flowchart LR
    subgraph Input
        A[Patient ID] --> C
        B[Symptoms] --> C
    end

    subgraph LangGraph["LangGraph State Machine"]
        C[gather_context] --> D[medical_board]
        D --> E{route_logic}
        E -->|RED| F[emergency]
        E -->|YELLOW| G[urgent]
        E -->|GREEN| H[routine]
        F --> R[qa_review]
        G --> R
        H --> R
    end

    subgraph CrewAI["CrewAI Agents (Primary Triage)"]
        D --> I[Triage Nurse]
        I --> J[ER Physician]
        J --> D
    end

    subgraph AutoGen["AutoGen Agents (QA Validation)"]
        R --> S[QA Reviewer]
        S --> T[Clinical Auditor]
        T --> R
    end

    subgraph MCP["MCP Tools"]
        I --> K[Patient Lookup]
        I --> L[Guideline Search]
        I --> M[Treatment Considerations]
    end

    subgraph Data["Databases"]
        K --> N[(Patient DB)]
        L --> O[(Protocol DB)]
        M --> P[(Contraindications)]
    end

    R --> Q[Final Output]
```

---

## Tech Stack

| Technology | Purpose | Description |
|------------|---------|-------------|
| ![LangGraph](https://img.shields.io/badge/LangGraph-00d4aa?style=flat-square&logo=langchain&logoColor=white) | **Orchestration** | State machine for workflow management with conditional routing |
| ![CrewAI](https://img.shields.io/badge/CrewAI-ff6b35?style=flat-square&logo=openai&logoColor=white) | **Primary Triage** | Collaborative AI agents (Triage Nurse + ER Physician) |
| ![AutoGen](https://img.shields.io/badge/AutoGen-a855f7?style=flat-square&logo=microsoft&logoColor=white) | **QA Validation** | Microsoft AutoGen agents (QA Reviewer + Clinical Auditor) |
| ![MCP](https://img.shields.io/badge/MCP-2563eb?style=flat-square&logo=anthropic&logoColor=white) | **Tool Protocol** | Model Context Protocol for structured tool interactions |
| ![Ollama](https://img.shields.io/badge/Ollama-7c3aed?style=flat-square&logo=meta&logoColor=white) | **LLM Runtime** | Local Llama 3.1 8B inference |
| ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white) | **API Layer** | High-performance async web framework |
| ![Python](https://img.shields.io/badge/Python-3776ab?style=flat-square&logo=python&logoColor=white) | **Language** | Python 3.11+ with type hints |
| ![UV](https://img.shields.io/badge/UV-de5fe9?style=flat-square&logo=astral&logoColor=white) | **Package Manager** | Fast, modern Python package management |

---

## Features

### Triage Protocols

| Level | Condition | Action |
|-------|-----------|--------|
| 🔴 **RED** | Chest pain with sweating/arm pain | Immediate emergency dispatch |
| 🟡 **YELLOW** | Fever, cough, respiratory symptoms | Urgent care referral |
| 🟢 **GREEN** | Localized rash, minor symptoms | Home care instructions |

### Treatment Considerations

The system analyzes patient history for:

- **Medication Allergies** (e.g., Penicillin → use Azithromycin instead)
- **Chronic Conditions** (e.g., Hypertension → avoid NSAIDs)
- **Previous Medical Events** (e.g., Prior stroke → rapid neuro assessment)

---

## Installation

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) with Llama 3.1 8B model
- [UV](https://github.com/astral-sh/uv) package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/PeakWhale/trident.git
cd trident

# Install dependencies
uv sync

# Pull the Ollama model
ollama pull llama3.1:8b

# Start the server
uv run python main.py
```

### Quick Start

```bash
# Open in browser
open http://localhost:8000
```

---

## Usage

### Web Interface

1. Navigate to `http://localhost:8000`
2. Select a test scenario or enter custom patient data
3. Click **Analyze** to run the triage assessment
4. View the decision, protocol applied, and treatment considerations

### API Endpoint

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "P-101", "symptoms": "chest pain and sweating"}'
```

**Response:**
```json
{
  "patient_id": "P-101",
  "symptoms": "chest pain and sweating",
  "diagnosis": "RED",
  "plan": "EMERGENCY RESPONSE: Dispatch ambulance immediately (911)\n\n[PENICILLIN ALLERGY]...",
  "qa_review": {
    "validated": true,
    "confidence": "HIGH",
    "notes": "Protocol adherence confirmed by AutoGen QA agents"
  }
}
```

---

## Project Structure

```
trident/
├── main.py                 # Application entry point
├── pyproject.toml          # Dependencies and project config
├── README.md               # This file
├── src/
│   ├── trident.py          # LangGraph workflow definition
│   ├── medical_crew.py     # CrewAI agents and tasks
│   ├── autogen_review.py   # AutoGen QA validation agents
│   ├── hospital_mcp.py     # MCP tools and databases
│   ├── llm_manager.py      # Ollama LLM configuration
│   └── server.py           # FastAPI application
└── static/
    ├── index.html          # Web UI
    ├── style.css           # Styling
    └── app.js              # Frontend logic
```

---

## How It Works

### 1. Context Gathering
```
Patient ID + Symptoms → gather_context node
                        ├── Retrieves patient record from Patient DB
                        └── Analyzes history for treatment considerations
```

### 2. Hybrid LLM Triage (Symptom Extraction + Protocol Lookup)
```
medical_board node → Hybrid Architecture
                     │
                     ├── Step 1: LLM Symptom Extraction (Llama 3.1)
                     │   └── Analyzes natural language → cardiac | respiratory | dermatological
                     │
                     ├── Step 2: Protocol Lookup (Deterministic)
                     │   └── Category → get_triage_guidelines() → RED | YELLOW | GREEN
                     │
                     └── Step 3: CrewAI Analysis
                         ├── Triage Nurse (uses MCP tools for context)
                         └── ER Physician (provides reasoning & treatment notes)
```

This hybrid approach combines LLM flexibility (understanding varied symptom descriptions) with protocol reliability (consistent triage decisions).

### 3. Conditional Routing
```
route_logic → Reads final_diagnosis
              ├── RED → emergency node → "Dispatch Ambulance"
              ├── YELLOW → urgent node → "Refer to Urgent Care"
              └── GREEN → routine node → "Home Care Instructions"
```

### 4. Action Node Execution
```
Action nodes → Generate action plan with treatment considerations
               ├── emergency → "Dispatch Ambulance" + treatment notes
               ├── urgent → "Urgent Care Referral" + treatment notes
               └── routine → "Home Care Instructions" + treatment notes
```

### 5. AutoGen QA Validation
```
qa_review node → AutoGen Sequential Process
                 ├── QA Reviewer (checks protocol compliance)
                 │   └── Verifies decision matches symptom-protocol rules
                 └── Clinical Auditor (validates and scores)
                     └── Outputs: VALIDATED + Confidence (HIGH/MEDIUM/LOW)
```

### 6. Final Output
```
Final Output = Triage Level + Action Plan + QA Validation
               ├── Diagnosis (RED/YELLOW/GREEN)
               ├── Action plan with treatment considerations
               └── QA review status and confidence score
```

---

## Test Scenarios

| Scenario | Patient | Symptoms | Expected |
|----------|---------|----------|----------|
| **Cardiac Emergency** | P-102 (82yo, stroke history) | Chest pain, sweating | 🔴 RED |
| **Respiratory Illness** | P-101 (45yo, hypertension) | Fever 101°F, cough | 🟡 YELLOW |
| **Minor Condition** | P-999 (25yo, healthy) | Skin rash from gardening | 🟢 GREEN |

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>PEAKWHALE™ TRIDENT</strong><br/>
  <sub>Intelligent Medical Triage • Multi-Agent AI • Protocol Compliance</sub>
</p>
