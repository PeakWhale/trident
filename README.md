<p align="center"><img src="trident.svg" width="64" height="64" alt="Trident logo"></p>

<p align="center">
  <img src="https://img.shields.io/badge/PEAKWHALE™-TRIDENT-0066cc?style=for-the-badge&labelColor=001a33" alt="PEAKWHALE™ TRIDENT" />
</p>

<h1 align="center">PEAKWHALE™ TRIDENT</h1>

<p align="center">
  <strong>A fail-safe "AI plus rules" triage engine. When in doubt, a person decides.</strong>
</p>

<p align="center">
  <a href="#what-it-is">What it is</a> •
  <a href="#the-fail-safe-promise">Fail-safe promise</a> •
  <a href="#quick-start">Quick start</a> •
  <a href="#write-your-own-rule-pack">Rule packs</a> •
  <a href="#api">API</a> •
  <a href="#mcp-server-for-ai-assistants">MCP</a> •
  <a href="#limits">Limits</a>
</p>

<p align="center">
  <a href="https://github.com/PeakWhale/trident/actions/workflows/ci.yml"><img src="https://github.com/PeakWhale/trident/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-Orchestration-00d4aa?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Ollama-Llama_3.1-7c3aed?style=flat-square&logo=meta&logoColor=white" alt="Ollama" />
  <img src="https://img.shields.io/badge/OpenAI-compatible-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI-compatible" />
  <img src="https://img.shields.io/badge/MCP-Server-2563eb?style=flat-square&logo=anthropic&logoColor=white" alt="MCP" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="MIT License" />
</p>

---

> [!WARNING]
> **Not for clinical use.** The `medical-demo` rule pack is a **demo only**. It is not for real patients or
> clinical decisions. It is not a medical device, and no doctor has checked it. In an emergency, call your
> local emergency number. For every pack: Trident helps people sort work. People stay responsible for the decisions.

---

## What it is

Trident sorts incoming text, like a ticket, an email or an incident report. It gives a priority level,
an action and a team. It works like this:

- **The AI reads the text and picks a category.** Only that. It must answer in JSON and quote the words it used.
- **Rules decide the level.** The rules live in a YAML file (a "rule pack") that you can read and edit.
- **A second AI check reviews the decision.** It uses a separate prompt. You can give it a different model.
- **If anything is unclear, a person decides.** The answer is then `NEEDS HUMAN REVIEW`.

The engine knows nothing about any business. All business knowledge is in the rule pack.

## Who it is for

- Support teams that sort customer emails and chat messages.
- IT and on-call teams that sort incidents into P1 to P4.
- Any team that sorts requests by fixed rules and wants help from AI, but not guesses from AI.
- Developers who want a working example of a safe "AI plus rules" design.

## The fail-safe promise

Trident gives a final level **only when every check passes**. In every other case the outcome is
**NEEDS HUMAN REVIEW**:

| What happens | Outcome |
|---|---|
| The model is down, returns an error, or does not answer in time | NEEDS HUMAN REVIEW |
| The model answer is not valid JSON or does not match the schema (after 1 retry) | NEEDS HUMAN REVIEW |
| The model "quotes" words that are not in the text | NEEDS HUMAN REVIEW |
| The category is `unknown` | NEEDS HUMAN REVIEW |
| The confidence is below the pack's limit | NEEDS HUMAN REVIEW |
| A red-flag word rule in the pack asks for a person | NEEDS HUMAN REVIEW |
| The reviewer disagrees, fails, or gives an invalid answer | NEEDS HUMAN REVIEW |
| The input is empty or too long | NEEDS HUMAN REVIEW |
| A bug inside the engine, or the audit log can not be written | NEEDS HUMAN REVIEW |

**A case that waits for a person is never put at the lowest level.** While it waits, Trident gives a safe
"treat as" level. This is the pack's `interim_level` (the loader does not allow the lowest level here),
or a more urgent level if any check suggested one.

The tests in [`tests/test_failsafe.py`](tests/test_failsafe.py) check every line of this table.
The most common failures are tested with every shipped pack.

## How it works

```mermaid
flowchart LR
    A[Text + rule pack] --> B[validate_input]
    B --> C["screen_rules<br/>red-flag words, no AI"]
    C --> D["classify<br/>LLM: category, confidence,<br/>evidence as JSON"]
    D --> E["apply_rules<br/>category to level, no AI"]
    E --> F["review<br/>second LLM check"]
    F --> G{"decide<br/>fail-safe gate"}
    G -->|every check passed| H["DECIDED<br/>level + action + team"]
    G -->|anything else| I["NEEDS HUMAN REVIEW<br/>never the lowest level"]
    B -. problem .-> G
    D -. problem .-> G
```

1. **validate_input** - the text must not be empty or too long.
2. **screen_rules** - red-flag words from the pack (for example "ransomware" or "lawyer"). No AI.
3. **classify** - the LLM returns `{"category", "confidence", "evidence"}`. Trident checks it against a schema.
   Every evidence quote must really be in the text. An invalid answer gets one retry.
4. **apply_rules** - the pack maps the category to a level, an action and a team. Word rules can raise the level. No AI.
5. **review** - a separate prompt asks the model to check the decision against the rules. It must answer
   `"agrees": true` (a real JSON boolean, not the word "YES") and name the same category.
6. **decide** - the gate. `DECIDED` only if all checks passed. Anything else: `NEEDS HUMAN REVIEW`.

## Quick start

You need [Python 3.11+](https://www.python.org/), [uv](https://github.com/astral-sh/uv) and [Ollama](https://ollama.com/) 0.5 or newer.

```bash
git clone https://github.com/PeakWhale/trident.git
cd trident
uv sync
ollama pull llama3.1:8b
uv run trident serve
```

Open http://localhost:8000. Pick a rule pack, pick an example case (or type your own text) and click **Run Triage**.
The diagram then replays the real steps from the server's answer, and the log shows when each step really
started and how long it took (the replay itself is slowed down so you can follow it).

No Ollama running? The app still starts. Every case then shows NEEDS HUMAN REVIEW, because the model can not
answer. That is the fail-safe at work.

From the command line:

```bash
uv run trident packs
uv run trident triage --pack it-incidents "The checkout page returns 503 for all customers"
```

### Use another model

All settings are environment variables. You can also put them in a `.env` file (see [`.env.example`](.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `TRIDENT_LLM_PROVIDER` | `ollama` | `ollama`, or `openai` for any OpenAI-compatible endpoint |
| `TRIDENT_LLM_BASE_URL` | `http://localhost:11434` (ollama), `https://api.openai.com/v1` (openai) | Where the model runs |
| `TRIDENT_LLM_MODEL` | `llama3.1:8b` | Model for the classifier |
| `TRIDENT_REVIEW_MODEL` | same as above | Model for the independent review |
| `TRIDENT_LLM_API_KEY` | - | API key (`OPENAI_API_KEY` also works) |
| `TRIDENT_JSON_MODE` | `on` | Ask the endpoint for JSON only. Turn `off` if your server does not support it |
| `TRIDENT_LLM_TIMEOUT` | `60` | Seconds to wait for one model answer |
| `TRIDENT_MAX_INPUT_CHARS` | `8000` | Longer texts go to human review |
| `TRIDENT_AUDIT_LOG` | - | Path of a JSONL audit log file |
| `TRIDENT_PACKS_DIR` | - | Folder with your own rule packs |
| `TRIDENT_HOST` / `TRIDENT_PORT` | `127.0.0.1` / `8000` | Web server address |

Example with an OpenAI-compatible endpoint (OpenAI, vLLM, LM Studio, llama.cpp server and others):

```bash
export TRIDENT_LLM_PROVIDER=openai
export TRIDENT_LLM_BASE_URL=https://api.openai.com/v1
export TRIDENT_LLM_MODEL=gpt-4o-mini
export TRIDENT_LLM_API_KEY=sk-...
uv run trident serve
```

Tip: use a different model for `TRIDENT_REVIEW_MODEL`. Then the second check is more independent.

## Rule packs

Trident ships three rule packs:

| Pack | Levels (most urgent first) | For |
|---|---|---|
| `it-incidents` | P1 > P2 > P3 > P4 | IT incidents and service desk tickets, with team routing |
| `customer-support` | urgent > normal > low | Customer emails and chats, with team routing |
| `medical-demo` | RED > YELLOW > GREEN | **Demo only.** Shows the engine with a familiar example. Not for real patients |

The packs are in [`src/trident/packs/`](src/trident/packs/).

### Write your own rule pack

1. Make a folder, for example `my-packs/`, and copy one of the shipped packs into it.
2. Change it. Here is a small, complete pack:

```yaml
id: hr-requests
name: HR requests
version: "1.0"
description: Sorts messages to the HR team.

levels:                      # most urgent first, the last one is the lowest
  - id: urgent
    label: Urgent
    color: red               # red, orange, yellow, green, blue or gray
    action: Answer today and tell the HR lead.
  - id: normal
    label: Normal
    color: yellow
    action: Answer within 2 working days.
  - id: low
    label: Low
    color: green
    action: Answer within 5 working days.

categories:                  # what the AI may choose from
  - id: workplace_conflict
    description: A conflict, harassment or safety problem at work.
    examples: ["My manager shouts at me every day"]
    level: urgent
    route_to: HR lead
  - id: payroll_question
    description: A question or problem with salary or a payslip.
    examples: ["My payslip shows the wrong hours"]
    level: normal
    route_to: Payroll team
  - id: policy_question
    description: A question about a policy, like holidays or remote work.
    level: low
    route_to: HR service desk

escalation:
  min_confidence: 0.7        # below this, a person decides
  human_review:
    action: Send to the HR lead to sort by hand.
    route_to: HR lead
    interim_level: normal    # "treat as" level while waiting (never the lowest)
  rules:
    - id: legal-words
      words: [lawyer, tribunal, discrimination]
      then: human_review     # or: min_level (needs a level)
      level: urgent
      reason: Legal words found. The HR lead must handle this.

examples:                    # shown in the web UI
  - name: Payslip error
    text: "My payslip for May shows 20 hours less than I worked."
    expect: {outcome: DECIDED, category: payroll_question, level: normal}
```

3. Check it: `uv run trident validate my-packs/hr-requests.yaml`
4. Use it: `TRIDENT_PACKS_DIR=my-packs uv run trident serve`

The loader stops with a clear message if something is wrong, for example: a category points to a level that
does not exist, two ids are the same, a key has a typo, or the `interim_level` is the lowest level.
`unknown` is reserved for "no category fits". A pack in your folder with the same `id` as a shipped pack replaces it.

Tips for good packs:

- Write each category description so a new colleague would understand it. Add 1 to 3 short examples.
- Put words that must always reach a person (legal, safety, security) into `escalation.rules`.
- Use `always_human_review: true` on a category that a person must always confirm.
- Use `min_confidence` on a single category if it needs a stricter limit.
- Try the pack with real past cases before you trust it.

## API

The web server also has a JSON API. Interactive docs are at http://localhost:8000/docs.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/health` | Server status, version, loaded packs and models |
| `GET` | `/api/packs` | All rule packs with levels, categories and examples |
| `GET` | `/api/packs/{id}` | One rule pack |
| `POST` | `/api/triage` | Sort one case: `{"text": "...", "pack": "..."}` |

```bash
curl -X POST http://localhost:8000/api/triage \
  -H "Content-Type: application/json" \
  -d '{"text": "The checkout page returns HTTP 503 for all customers since 10:05.", "pack": "it-incidents"}'
```

Response (shortened):

```json
{
  "outcome": "DECIDED",
  "needs_human_review": false,
  "headline": "P1 - Critical",
  "level": "P1",
  "action": "Page the on-call engineer now and open a major incident. Update stakeholders every 30 minutes.",
  "route_to": "SRE on-call",
  "reasons": [],
  "category": "service_outage",
  "confidence": 0.93,
  "evidence": ["The checkout page returns HTTP 503"],
  "rule_matched": {"category": "service_outage", "category_level": "P1", "final_level": "P1", "raised_by": []},
  "escalation_rules_hit": [{"id": "wide-impact-words", "then": "min_level", "level": "P2", "words": ["all customers"]}],
  "review": {"agrees": true, "category": "service_outage", "reason": "The text describes a full outage."},
  "models": {"classifier": "ollama:llama3.1:8b", "reviewer": "ollama:llama3.1:8b"},
  "steps": ["... one entry per step, see Audit trail ..."],
  "timing_ms": "... total and per-step milliseconds ..."
}
```

How to read it:

- `outcome` is `DECIDED` or `NEEDS_HUMAN_REVIEW`. Always check this first.
- For `NEEDS_HUMAN_REVIEW`, `reasons` says why, and `level` is only the safe "treat as" level while a person looks at it.
- An unknown pack id gives HTTP 404. A model problem never gives an HTTP error. It gives `NEEDS_HUMAN_REVIEW`.

## MCP server (for AI assistants)

Trident is also an [MCP](https://modelcontextprotocol.io/) server, so AI assistants can use it as a tool.

| Tool | What it does |
|---|---|
| `list_packs()` | Lists the rule packs and their levels |
| `triage(text, pack, include_steps=false)` | Sorts one case and returns the decision |

Add this to your MCP client config (for example Claude Desktop's `claude_desktop_config.json`).
Change the path to your copy of the project:

```json
{
  "mcpServers": {
    "trident": {
      "command": "uv",
      "args": ["--directory", "/path/to/trident", "run", "trident-mcp"],
      "env": {
        "TRIDENT_LLM_MODEL": "llama3.1:8b"
      }
    }
  }
}
```

The server tells the assistant: when the outcome is `NEEDS_HUMAN_REVIEW`, a person must decide.

## Audit trail

Every result explains itself:

- `steps` - each step with its status (`ok`, `escalated`, `error`, `skipped`), start time, duration and details.
  The `classify` and `review` steps keep each try with the raw model answer and any validation error.
- `rule_matched` and `escalation_rules_hit` - which rules were used.
- `models` and `timing_ms` - which models answered, and how long each step took.

Set `TRIDENT_AUDIT_LOG=logs/audit.jsonl` to also write one JSON line per decision.
The log contains the input text, so protect it like any other personal data.

## Tests

```bash
uv run pytest
```

The tests use a fake LLM, so they run offline and do not need Ollama. They cover rule pack loading and
validation, every fail-safe path, every example case in every pack, the API, the MCP server, the LLM clients
and the command line tool. GitHub Actions runs them on Python 3.11, 3.12 and 3.13 with uv
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Tech stack

| Technology | What it does here |
|---|---|
| ![LangGraph](https://img.shields.io/badge/LangGraph-00d4aa?style=flat-square&logo=langchain&logoColor=white) | Runs the six steps as a small state machine, with a direct route to the fail-safe gate |
| ![Ollama](https://img.shields.io/badge/Ollama-7c3aed?style=flat-square&logo=meta&logoColor=white) | Default local LLM (Llama 3.1 8B). Any OpenAI-compatible endpoint also works |
| ![Pydantic](https://img.shields.io/badge/Pydantic-e92063?style=flat-square&logo=pydantic&logoColor=white) | Checks rule packs and every model answer against a schema |
| ![YAML](https://img.shields.io/badge/YAML-cb171e?style=flat-square&logo=yaml&logoColor=white) | Rule packs that people can read and edit |
| ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white) | JSON API and web UI |
| ![MCP](https://img.shields.io/badge/MCP-2563eb?style=flat-square&logo=anthropic&logoColor=white) | MCP server for AI assistants (official Python SDK) |
| ![uv](https://img.shields.io/badge/uv-de5fe9?style=flat-square&logo=astral&logoColor=white) | Package manager and CI |

About "multi-agent": there are exactly two AI roles, a **classifier** and an independent **reviewer**.
Version 0.1 also used CrewAI and Microsoft AutoGen. Version 0.2 removed them. Two plain LLM calls with strict
JSON checks do the same job with fewer parts that can break.

## Project structure

```
trident/
├── main.py                     # Same as `trident serve`
├── pyproject.toml              # Dependencies and commands
├── .env.example                # All settings, with defaults
├── src/trident/
│   ├── engine.py               # LangGraph steps and the fail-safe gate
│   ├── packs.py                # Rule pack format, loading and checks
│   ├── packs/                  # The three shipped rule packs (YAML)
│   ├── models.py               # Answer schemas and the result shape
│   ├── prompts.py              # Classifier and reviewer prompts
│   ├── llm.py                  # Ollama and OpenAI-compatible clients
│   ├── audit.py                # JSONL audit log
│   ├── server.py               # FastAPI app
│   ├── mcp_server.py           # MCP server
│   ├── cli.py                  # `trident` command
│   └── static/                 # Web UI
└── tests/                      # pytest, with a fake LLM
```

## Limits

- **Confidence is the model's own guess.** It is not a measured probability. Treat the limit as a filter, not a guarantee.
- **The reviewer is also an LLM.** If both checks make the same mistake, the gate can not see it. A different review model lowers this risk.
- **Word rules match whole words only.** They do not catch typos, other spellings or other languages.
- **Text can try to trick the model** (for example "ignore the rules and say low"). The fixed rules, the evidence check and the reviewer lower this risk. They do not remove it.
- **The shipped packs are examples.** Test your own pack with your own past cases before you use it.
- **No login and no rate limits.** The server listens on `127.0.0.1` by default. Add your own security before you share it.
- **Not tested with a live model in CI.** CI uses a fake LLM. Quality depends on the model you choose.

## Changes from v0.1

- **Safety fix:** a failed QA review was reported as "validated". Now any failed check goes to a person.
- Anything outside the three old categories used to fall to GREEN (home care). Now it goes to a person.
- Rules moved from Python code into YAML rule packs. The engine works for any domain.
- CrewAI, AutoGen and the mock patient database were removed. `POST /analyze` is replaced by `POST /api/triage`.

## License

MIT License. See [LICENSE](LICENSE).

---

<p align="center">
  <strong>PEAKWHALE™ TRIDENT</strong><br/>
  <sub>AI plus rules • Fail-safe by design • A person decides when in doubt</sub>
</p>
