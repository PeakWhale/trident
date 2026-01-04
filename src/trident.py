from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from medical_crew import run_medical_analysis
from hospital_mcp import get_patient_record, get_treatment_considerations


class TridentState(TypedDict):
    patient_id: str
    symptoms: str
    patient_history: str
    treatment_considerations: str
    final_diagnosis: str
    action_plan: str


def gather_patient_context(state: TridentState):
    """First node: Gather patient history and treatment considerations."""
    patient_id = state['patient_id']
    
    # Get patient record
    patient_history = get_patient_record(patient_id)
    print(f"\n📋 [TRIDENT] Retrieved patient record: {patient_history}")
    
    # Get treatment considerations based on history
    treatment_considerations = get_treatment_considerations(patient_id)
    print(f"\n💊 [TRIDENT] Treatment considerations: {treatment_considerations[:100]}...")
    
    return {
        "patient_history": patient_history,
        "treatment_considerations": treatment_considerations
    }


def call_medical_crew(state: TridentState):
    """Second node: Run AI agents to determine triage level."""
    print(f"\n🔱 [TRIDENT] Activating Medical CrewAI Team (Llama 3.1)...")
    
    # Pass both symptoms and patient history to the medical crew
    result = run_medical_analysis(
        state['symptoms'], 
        state['patient_id'],
        state.get('patient_history', '')
    )
    
    # Parse Result
    text = str(result).upper()
    level = "GREEN"
    if "RED" in text: level = "RED"
    elif "YELLOW" in text: level = "YELLOW"
        
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
    
    # Add treatment considerations from patient history
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_urgent(state: TridentState):
    """YELLOW path: Urgent care referral with treatment considerations."""
    base_plan = "URGENT CARE: Refer to urgent care facility within 2 hours"
    
    # Add treatment considerations from patient history
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_routine(state: TridentState):
    """GREEN path: Home care with treatment considerations."""
    base_plan = "ROUTINE CARE: Home care instructions with follow-up as needed"
    
    # Add treatment considerations from patient history
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


# Build the workflow
workflow = StateGraph(TridentState)

# Add nodes
workflow.add_node("gather_context", gather_patient_context)
workflow.add_node("medical_board", call_medical_crew)
workflow.add_node("emergency", node_emergency)
workflow.add_node("urgent", node_urgent)
workflow.add_node("routine", node_routine)

# Set entry point and edges
workflow.set_entry_point("gather_context")
workflow.add_edge("gather_context", "medical_board")
workflow.add_conditional_edges("medical_board", route_logic, {
    "emergency": "emergency", "urgent": "urgent", "routine": "routine"
})
workflow.add_edge("emergency", END)
workflow.add_edge("urgent", END)
workflow.add_edge("routine", END)

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
        "action_plan": ""
    })
