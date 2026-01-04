from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from hospital_mcp import get_patient_record, get_triage_guidelines, get_treatment_considerations
from llm_manager import get_ollama


# Wrap functions as Tools
@tool("Patient Lookup")
def tool_lookup(patient_id: str):
    """Consults the hospital database for patient history."""
    return get_patient_record(patient_id)


@tool("Guideline Search")
def tool_guidelines(symptom: str):
    """Checks medical protocols for triage level determination."""
    return get_triage_guidelines(symptom)


@tool("Treatment Considerations")
def tool_treatment(patient_id: str):
    """Gets treatment considerations based on patient medical history."""
    return get_treatment_considerations(patient_id)


def run_medical_analysis(symptom_text: str, patient_id: str, patient_history: str = ""):
    """Run the medical analysis crew with Ollama LLM"""
    llm_engine = get_ollama()
    
    # Agents
    nurse = Agent(
        role='Triage Nurse',
        goal='Gather patient history and lookup triage guidelines. Report the EXACT protocol output from Guideline Search tool.',
        backstory='''You are a triage nurse who STRICTLY follows protocol outputs.

CRITICAL RULES:
1. Use Guideline Search tool with the PRIMARY symptom keyword (rash, chest, fever, etc.)
2. The Guideline Search tool output is AUTHORITATIVE - copy it exactly
3. If tool says "GREEN PROTOCOL" -> report GREEN
4. If tool says "YELLOW PROTOCOL" -> report YELLOW
5. If tool says "RED PROTOCOL" -> report RED
6. NEVER override or interpret the protocol - just report what the tool says
7. A rash/skin issue is GREEN, NOT an emergency''',
        llm=llm_engine,
        tools=[tool_lookup, tool_guidelines, tool_treatment],
        verbose=True
    )

    doctor = Agent(
        role='Emergency Physician',
        goal='Output the EXACT triage level from the protocol. Do NOT override protocol decisions.',
        backstory='''You are an ER doctor who MUST output the triage level from the nurse's protocol findings.

ABSOLUTE RULES - NO EXCEPTIONS:
1. If nurse reports "GREEN PROTOCOL" -> You MUST output "TRIAGE LEVEL: GREEN"
2. If nurse reports "YELLOW PROTOCOL" -> You MUST output "TRIAGE LEVEL: YELLOW"
3. If nurse reports "RED PROTOCOL" -> You MUST output "TRIAGE LEVEL: RED"
4. You are NOT allowed to change the level. The protocol is law.
5. Skin rash = GREEN. Fever/cough = YELLOW. Chest pain = RED.
6. Do NOT escalate GREEN to YELLOW or RED based on your judgment.''',
        llm=llm_engine,
        verbose=True
    )

    # Tasks
    task1 = Task(
        description=f"""Patient {patient_id} reports: '{symptom_text}'.

STEPS:
1. Identify the PRIMARY symptom from the patient statement:
   - If mentions rash, skin, itch, gardening -> use "rash" as search term
   - If mentions fever, cough, breathing -> use "fever" as search term
   - If mentions chest pain, arm pain, sweating -> use "chest" as search term
2. Use Guideline Search tool with that PRIMARY symptom keyword
3. The tool will return a PROTOCOL (GREEN, YELLOW, or RED) - this is the ANSWER
4. Report the exact protocol output - do not interpret or change it

IMPORTANT: A rash is GREEN, not an emergency. Trust the Guideline Search tool output.""",
        expected_output="The exact protocol output from Guideline Search (GREEN PROTOCOL, YELLOW PROTOCOL, or RED PROTOCOL).",
        agent=nurse
    )
    
    task2 = Task(
        description="""Look at the nurse's protocol finding and output the SAME level.

RULES:
- If nurse found GREEN PROTOCOL -> output "TRIAGE LEVEL: GREEN"
- If nurse found YELLOW PROTOCOL -> output "TRIAGE LEVEL: YELLOW"
- If nurse found RED PROTOCOL -> output "TRIAGE LEVEL: RED"

DO NOT change the level. DO NOT use your own judgment. Just copy what the protocol says.

Output format:
TRIAGE LEVEL: [exactly what protocol says]
TREATMENT NOTES: [any notes from patient history]""",
        expected_output="TRIAGE LEVEL: GREEN or YELLOW or RED (matching the protocol)",
        agent=doctor
    )

    crew = Crew(agents=[nurse, doctor], tasks=[task1, task2], process=Process.sequential)
    return crew.kickoff()
