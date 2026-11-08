"""Honest scaffold endpoints. Agent 2 replaces the explicit 501s during integration."""

from fastapi import FastAPI, HTTPException

from app.contracts import HealthResponse, RunResult, TrialInput

app = FastAPI(title="TrialFair", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Indicate scaffold readiness without claiming live agents are implemented."""
    return HealthResponse()


@app.post("/runs", response_model=RunResult)
async def create_run(trial_input: TrialInput) -> RunResult:
    """Input validation works now; do not pretend an investigation occurred."""
    raise HTTPException(status_code=501, detail="Agent pipeline has not been implemented")


@app.get("/runs/{run_id}", response_model=RunResult)
def get_run(run_id: str) -> RunResult:
    """Storage is an explicit integration task for Agent 2."""
    raise HTTPException(status_code=501, detail="Run storage has not been implemented")
