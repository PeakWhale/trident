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
        goal='Gather patient history and lookup triage guidelines. Report the protocol AND any treatment considerations from patient history.',
        backstory='''You are an experienced triage nurse who:
1. ALWAYS uses the Guideline Search tool to find the correct triage protocol based on PRIMARY symptom
2. ALWAYS uses the Patient Lookup tool to get patient medical history
3. ALWAYS uses the Treatment Considerations tool to identify contraindications and monitoring needs
4. Reports both the triage protocol AND any treatment considerations from patient history''',
        llm=llm_engine,
        tools=[tool_lookup, tool_guidelines, tool_treatment],
        verbose=True
    )

    doctor = Agent(
        role='Emergency Physician',
        goal='Determine the EXACT triage level (RED, YELLOW, or GREEN) based on protocols AND acknowledge treatment considerations from patient history',
        backstory='''You are a senior ER doctor who:
1. MUST follow clinical protocols exactly for triage level
2. MUST acknowledge treatment considerations from patient history
3. If protocol says RED, output RED. If YELLOW, output YELLOW. If GREEN, output GREEN.
4. You never override protocols but you DO note treatment considerations.''',
        llm=llm_engine,
        verbose=True
    )

    # Tasks
    task1 = Task(
        description=f"""Patient {patient_id} reports: '{symptom_text}'.

Your tasks:
1. Use Patient Lookup tool to get patient history for {patient_id}
2. Use Treatment Considerations tool for {patient_id} to get any contraindications or monitoring needs
3. Identify the PRIMARY symptom (chest pain OR fever/cough OR rash)
4. Use Guideline Search tool to lookup the triage protocol for that symptom
5. Report BOTH:
   - The triage protocol and recommended level (RED, YELLOW, or GREEN)
   - Any treatment considerations from patient history (allergies, contraindications, monitoring needs)""",
        expected_output="The protocol with triage level (RED/YELLOW/GREEN) AND any treatment considerations from patient history.",
        agent=nurse
    )
    
    task2 = Task(
        description="""Review the nurse's findings and:
1. Confirm the EXACT triage level from the protocol (RED, YELLOW, or GREEN)
2. Acknowledge any treatment considerations from patient history

Output format:
TRIAGE LEVEL: [RED/YELLOW/GREEN]
TREATMENT NOTES: [Any considerations from patient history]""",
        expected_output="The triage level (RED, YELLOW, or GREEN) with any treatment notes from patient history.",
        agent=doctor
    )

    crew = Crew(agents=[nurse, doctor], tasks=[task1, task2], process=Process.sequential)
    return crew.kickoff()
