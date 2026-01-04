
# Silence LiteLLM telemetry/logging noise
import os
import sys
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_PROXY"] = "False"

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from trident import process_patient_request
import uvicorn
import io
import contextlib

app = FastAPI()

class PatientRequest(BaseModel):
    patient_id: str
    symptoms: str

@app.post("/analyze")
async def analyze_patient(request: PatientRequest):
    try:
        # Capture stdout to get logs from CrewAI/LangGraph
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            print(f"Received request for {request.patient_id}: {request.symptoms}")
            result = process_patient_request(request.patient_id, request.symptoms)
        
        logs = f.getvalue()
        
        diagnosis = result.get("final_diagnosis", "UNKNOWN")
        plan = result.get("action_plan", "No plan generated")
        
        # AutoGen QA Review results
        qa_validated = result.get("qa_validated", False)
        qa_confidence = result.get("qa_confidence", "N/A")
        qa_notes = result.get("qa_notes", "")
        
        return {
            "status": "success",
            "diagnosis": diagnosis,
            "plan": plan,
            "patient_id": request.patient_id,
            "logs": logs,
            # AutoGen QA Review
            "qa_review": {
                "validated": qa_validated,
                "confidence": qa_confidence,
                "notes": qa_notes[:500] if qa_notes else ""
            }
        }
    except Exception as e:
        error_str = str(e)
        print(f"Error processing request: {error_str}")
        raise HTTPException(status_code=500, detail=error_str)

# Mount static files - mount after API routes to avoid conflicts
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Mount static files with html=True to serve index.html for root
# This should be last to allow API routes to take precedence
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
