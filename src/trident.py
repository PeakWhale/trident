from typing import TypedDict
import requests
import json
from langgraph.graph import StateGraph, END
from medical_crew import run_medical_analysis
from hospital_mcp import get_patient_record, get_treatment_considerations, get_triage_guidelines
from autogen_review import run_qa_review, get_review_summary


def llm_extract_primary_symptom(symptoms: str) -> str:
    """
    Use LLM to extract the primary symptom category from natural language.
    This is where the LLM adds value - understanding varied symptom descriptions.

    Returns one of: 'cardiac', 'respiratory', 'dermatological', or 'unknown'
    """
    prompt = f"""You are a medical triage assistant. Analyze the patient's symptoms and classify into ONE category.

SYMPTOM CATEGORIES:
- cardiac: chest pain, arm pain, sweating/diaphoresis, crushing sensation, radiating pain, heart-related
- respiratory: fever, cough, breathing difficulty, shortness of breath, low oxygen/SPO2
- dermatological: rash, itching, skin irritation, hives, localized skin issues

PATIENT SYMPTOMS: {symptoms}

Respond with ONLY ONE WORD - the category name (cardiac, respiratory, or dermatological).
If unclear, respond with the most likely category based on the symptoms described.

CATEGORY:"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.1:8b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}  # Low temperature for consistency
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json().get("response", "").strip().lower()
            # Extract just the category word
            for category in ['cardiac', 'respiratory', 'dermatological']:
                if category in result:
                    return category

        return "unknown"
    except Exception as e:
        print(f"[TRIDENT] LLM extraction failed: {e}")
        return "unknown"


def keyword_fallback(symptoms: str) -> str:
    """Fallback keyword matching if LLM extraction fails."""
    s = symptoms.lower()
    if any(kw in s for kw in ['rash', 'itch', 'skin', 'gardening']):
        return "dermatological"
    elif any(kw in s for kw in ['fever', 'cough', 'breath', 'spo2', 'respiratory']):
        return "respiratory"
    elif any(kw in s for kw in ['chest', 'arm pain', 'sweating', 'diaphoresis', 'crushing', 'radiating']):
        return "cardiac"
    return "unknown"


def determine_triage_level(symptoms: str) -> tuple[str, str]:
    """
    HYBRID APPROACH: LLM extracts symptom category, rules apply protocol.

    1. LLM analyzes natural language to extract primary symptom category
    2. If LLM fails, fall back to keyword matching
    3. Protocol rules determine the triage level based on category

    Returns: (triage_level, extracted_category)
    """
    # Step 1: LLM extracts the symptom category
    print(f"\n[TRIDENT] LLM analyzing symptoms...")
    category = llm_extract_primary_symptom(symptoms)
    print(f"[TRIDENT] LLM extracted category: {category}")

    # Step 2: Fallback if LLM couldn't classify
    if category == "unknown":
        print(f"[TRIDENT] Using keyword fallback...")
        category = keyword_fallback(symptoms)
        print(f"[TRIDENT] Fallback category: {category}")

    # Step 3: Map category to guideline search term
    category_to_symptom = {
        "cardiac": "chest",
        "respiratory": "fever",
        "dermatological": "rash",
        "unknown": symptoms[:50]
    }
    search_term = category_to_symptom.get(category, symptoms[:50])

    # Step 4: Get authoritative guideline (deterministic)
    guideline = get_triage_guidelines(search_term)
    print(f"[TRIDENT] Protocol: {guideline}")

    # Step 5: Extract level from guideline
    if "RED PROTOCOL" in guideline:
        return "RED", category
    elif "YELLOW PROTOCOL" in guideline:
        return "YELLOW", category
    elif "GREEN PROTOCOL" in guideline:
        return "GREEN", category
    else:
        return "GREEN", category


class TridentState(TypedDict):
    patient_id: str
    symptoms: str
    patient_history: str
    treatment_considerations: str
    final_diagnosis: str
    action_plan: str
    # AutoGen QA Review fields
    qa_validated: bool
    qa_confidence: str
    qa_notes: str


def gather_patient_context(state: TridentState):
    """First node: Gather patient history and treatment considerations."""
    patient_id = state['patient_id']
    
    # Get patient record
    patient_history = get_patient_record(patient_id)
    print(f"\n[TRIDENT] Retrieved patient record: {patient_history}")
    
    # Get treatment considerations based on history
    treatment_considerations = get_treatment_considerations(patient_id)
    print(f"\n[TRIDENT] Treatment considerations: {treatment_considerations[:100]}...")
    
    return {
        "patient_history": patient_history,
        "treatment_considerations": treatment_considerations
    }


def call_medical_crew(state: TridentState):
    """Second node: LLM-powered symptom extraction + CrewAI analysis."""

    # HYBRID: LLM extracts symptom category, protocol determines level
    level, category = determine_triage_level(state['symptoms'])
    print(f"\n[TRIDENT] Triage level: {level} (category: {category})")

    # Run CrewAI agents for detailed analysis and treatment notes
    print(f"\n[CREWAI] Activating Medical Team (Triage Nurse + ER Physician)...")
    result = run_medical_analysis(
        state['symptoms'],
        state['patient_id'],
        state.get('patient_history', '')
    )

    return {"final_diagnosis": level}


def route_logic(state: TridentState):
    """Route to appropriate action node based on diagnosis."""
    level = state.get('final_diagnosis', 'GREEN')
    if level == "RED": return "emergency"
    elif level == "YELLOW": return "urgent"
    else: return "routine"


def node_emergency(state: TridentState):
    """RED path: Emergency response with treatment considerations."""
    base_plan = "EMERGENCY RESPONSE: Dispatch ambulance immediately (911)"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_urgent(state: TridentState):
    """YELLOW path: Urgent care referral with treatment considerations."""
    base_plan = "URGENT CARE: Refer to urgent care facility within 2 hours"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_routine(state: TridentState):
    """GREEN path: Home care with treatment considerations."""
    base_plan = "ROUTINE CARE: Home care instructions with follow-up as needed"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def autogen_qa_review(state: TridentState):
    """
    Final node: AutoGen Quality Assurance Review
    
    Uses Microsoft AutoGen agents (QA Reviewer + Clinical Auditor)
    to validate the CrewAI triage decision.
    """
    print(f"\n[AUTOGEN] Running QA Review (QA Reviewer + Clinical Auditor)...")
    
    review_result = run_qa_review(
        symptoms=state['symptoms'],
        crewai_decision=state['final_diagnosis'],
        patient_history=state.get('patient_history', ''),
        treatment_considerations=state.get('treatment_considerations', '')
    )
    
    print(get_review_summary(review_result))
    
    return {
        "qa_validated": review_result['validated'],
        "qa_confidence": review_result['confidence'],
        "qa_notes": review_result['review_notes']
    }


# Build the workflow
workflow = StateGraph(TridentState)

# Add nodes
workflow.add_node("gather_context", gather_patient_context)
workflow.add_node("medical_board", call_medical_crew)  # CrewAI
workflow.add_node("emergency", node_emergency)
workflow.add_node("urgent", node_urgent)
workflow.add_node("routine", node_routine)
workflow.add_node("qa_review", autogen_qa_review)  # AutoGen

# Set entry point and edges
workflow.set_entry_point("gather_context")
workflow.add_edge("gather_context", "medical_board")
workflow.add_conditional_edges("medical_board", route_logic, {
    "emergency": "emergency", "urgent": "urgent", "routine": "routine"
})
# All action nodes flow to QA review
workflow.add_edge("emergency", "qa_review")
workflow.add_edge("urgent", "qa_review")
workflow.add_edge("routine", "qa_review")
workflow.add_edge("qa_review", END)

# Compile
app = workflow.compile()


def process_patient_request(patient_id, symptoms):
    """Main entry point for processing a patient triage request."""
    return app.invoke({
        "patient_id": patient_id, 
        "symptoms": symptoms,
        "patient_history": "",
        "treatment_considerations": "",
        "final_diagnosis": "",
        "action_plan": "",
        "qa_validated": False,
        "qa_confidence": "",
        "qa_notes": ""
    })
