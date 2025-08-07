# ZetaCore.py: Main FastAPI Orchestrator for Modular Scheduling System
# This file powers on your system, connecting Agent Z, Fetcher, Scheduler, and Neura-Z.

from fastapi import FastAPI, Body, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from agent_z import agent_z_handler, parse_future_date
from fetcher import fetch_availability_structured
from scheduler import schedule_event_from_schema
from neura_z import neura_z_respond, neura_z_brain
from fetch_availability import get_user_timezone
import datetime
import pytz
from typing import Optional
from uuid import uuid4

app = FastAPI()

# In-memory session store: {session_id: {slots}}
session_store = {}

@app.post("/zeta/chat")
def zeta_chat_endpoint(
    prompt: str = Body(...),
    session_id: Optional[str] = Body(None),
    request: Request = None
):
    """
    Main chat endpoint: runs Agent Z, Fetcher, Scheduler, and Neura-Z as needed.
    Maintains session state for slot-filling.
    """    # Backend determines if an existing session is used or a new one is created
    used_existing_session = False
    if session_id:
        sid = session_id
        if sid not in session_store:
            session = {}
            print(f"Starting new session with provided session_id: {sid}")
        else:
            session = session_store.get(sid, {})
            used_existing_session = True
            print(f"Using existing session: {sid}")
    else:
        sid = str(uuid4())
        session = {}
        print(f"Starting new session (no session_id provided): {sid}")

    user_timezone = get_user_timezone() or "UTC"
    now = datetime.datetime.now(pytz.timezone(user_timezone))
    # For demo, fetch 30 days of events for context
    calendar_events = fetch_availability_structured(days_range=30)["events"]

    def fetcher_wrapper(resolved_date, user_timezone):
        # Use Fetcher to get availability for a specific date
        return fetch_availability_structured(date=resolved_date.date().isoformat(), calendar_events=calendar_events)

    def scheduler_wrapper(schema, user_timezone):
        # Use Scheduler to schedule a meeting
        return schedule_event_from_schema(schema, user_timezone)
        
    def llm_wrapper(message, schema):
        # Always use the merged session schema for LLM context
        merged_schema = {**session, **schema}
        resolved_date = None
        if merged_schema.get("date"):
            resolved_date = parse_future_date(merged_schema["date"], user_timezone, now)
        elif merged_schema.get("relative_reference") and merged_schema["relative_reference"].get("event_title"):
            from agent_z import find_event_date_by_title
            anchor_date = find_event_date_by_title(merged_schema["relative_reference"]["event_title"], calendar_events)
            if anchor_date:
                offset = merged_schema["relative_reference"].get("offset")
                days_offset = 0
                if offset:
                    import re
                    match = re.search(r"(\d+)", offset)
                    if match:
                        days_offset = int(match.group(1))
                    elif "two" in offset:
                        days_offset = 2
                    else:
                        days_offset = 1
                anchor_dt = datetime.datetime.strptime(anchor_date, "%Y-%m-%d")
                resolved_date = anchor_dt + datetime.timedelta(days=days_offset)
        availability = None
        if resolved_date:
            date_str = resolved_date.date().isoformat() if hasattr(resolved_date, 'date') else str(resolved_date)
            availability = fetch_availability_structured(date=date_str, calendar_events=calendar_events)
        return neura_z_respond(message, availability=availability, user_timezone=user_timezone, current_schema=merged_schema)    # --- First use the Brain to analyze complex queries ---
    # Use the brain to interpret complex or vague queries
    merged_schema = session.copy()
    brain_analysis = neura_z_brain(prompt, user_timezone, merged_schema)
      # Extract insights from brain analysis to enhance the user query
    enhanced_prompt = prompt
    brain_insights = {}    # Add extracted details from brain to the insights
    if brain_analysis.get("extracted_date"):
        brain_insights["date"] = brain_analysis["extracted_date"]
    
    if brain_analysis.get("extracted_duration"):
        brain_insights["duration"] = brain_analysis["extracted_duration"]
        print(f"DEBUG: Duration detected and added to brain_insights: {brain_analysis['extracted_duration']}")
    
    if brain_analysis.get("extracted_title"):
        brain_insights["event_title"] = brain_analysis["extracted_title"]
        
    if brain_analysis.get("user_confirmation") is not None:
        brain_insights["user_confirmation"] = brain_analysis["user_confirmation"]
        
    # Check if brain detected all required details are available
    if brain_analysis.get("all_details_available") is True:
        brain_insights["all_details_available"] = True
        
    # Handle time constraints specially - convert to structured info
    if brain_analysis.get("extracted_time_constraint"):
        time_constraint = brain_analysis["extracted_time_constraint"]
        # Simple time extraction for "before X" or "after X" patterns
        import re
        before_match = re.search(r'before\s+(\d+(?::\d+)?\s*[AP]M)', time_constraint, re.IGNORECASE)
        after_match = re.search(r'after\s+(\d+(?::\d+)?\s*[AP]M)', time_constraint, re.IGNORECASE)
        exact_match = re.search(r'at\s+(\d+(?::\d+)?\s*[AP]M)', time_constraint, re.IGNORECASE)
        
        if before_match:
            # For "before X", we could suggest a time 1-2 hours before the constraint
            brain_insights["time_constraint"] = f"before {before_match.group(1)}"
        elif after_match:
            # For "after X", we could suggest that time or slightly after
            brain_insights["time_constraint"] = f"after {after_match.group(1)}"
            brain_insights["time"] = after_match.group(1)
        elif exact_match:
            # If it's an exact time, use it directly
            brain_insights["time"] = exact_match.group(1)
    
    # Store brain analysis in the session for context
    merged_schema["brain_analysis"] = brain_insights
    
    # --- Now pass everything to Agent Z ---
    # Always pass the session schema to Agent Z and only update with new non-None values
    agent_result = agent_z_handler(
        prompt,
        calendar_events,
        fetcher_wrapper,
        scheduler_wrapper,
        llm_wrapper,
        user_timezone,
        now,
        initial_schema=merged_schema
    )
    
    # Update session with the merged schema from agent_z_handler
    # Agent Z has already done the proper deep merging of the schema
    session = agent_result.get("schema", {})
    session_store[sid] = session

    # If meeting is scheduled, reset session
    if agent_result["action"] == "schedule_meeting":
        session_store.pop(sid, None)
    # Always use the latest session schema for LLM context
    latest_schema = session.copy()

    # Include brain analysis for better context
    brain_interpreted_intent = brain_analysis.get("interpreted_intent", "")
    brain_clarifications = brain_analysis.get("clarification_needed", [])
    brain_suggestions = brain_analysis.get("suggested_questions", [])

    response = None
    if agent_result["action"] == "show_availability":
        resolved_date = None
        if latest_schema.get("date"):
            resolved_date = parse_future_date(latest_schema["date"], user_timezone, now)
        elif latest_schema.get("relative_reference") and latest_schema["relative_reference"].get("event_title"):
            from agent_z import find_event_date_by_title
            anchor_date = find_event_date_by_title(latest_schema["relative_reference"]["event_title"], calendar_events)
            if anchor_date:
                offset = latest_schema["relative_reference"].get("offset")
                days_offset = 0
                if offset:
                    import re
                    match = re.search(r"(\d+)", offset)
                    if match:
                        days_offset = int(match.group(1))
                    elif "two" in offset:
                        days_offset = 2
                    else:
                        days_offset = 1
                anchor_dt = datetime.datetime.strptime(anchor_date, "%Y-%m-%d")
                resolved_date = anchor_dt + datetime.timedelta(days=days_offset)
        availability = None
        if resolved_date:
            date_str = resolved_date.date().isoformat() if hasattr(resolved_date, 'date') else str(resolved_date)
            availability = fetch_availability_structured(date=date_str, calendar_events=calendar_events)
        else:
            availability = None
        # Add brain interpretation to the schema for Neura-Z to use
        brain_enhanced_schema = latest_schema.copy()
        brain_enhanced_schema["brain_interpretation"] = brain_interpreted_intent
        brain_enhanced_schema["brain_clarifications_needed"] = brain_clarifications
        brain_enhanced_schema["brain_suggested_questions"] = brain_suggestions
        # Pass the updated schema to Neura-Z
        response = neura_z_respond(prompt, availability=availability, user_timezone=user_timezone, current_schema=brain_enhanced_schema)
    elif agent_result["action"] == "schedule_meeting":
        # Add brain interpretation for better confirmation messages
        brain_enhanced_schema = latest_schema.copy()
        brain_enhanced_schema["brain_interpretation"] = brain_interpreted_intent
        response = neura_z_respond(prompt, meeting_confirmation=agent_result["event"], user_timezone=user_timezone, current_schema=brain_enhanced_schema)
    else:
        # Always use enhanced schema with brain analysis for context
        brain_enhanced_schema = latest_schema.copy()
        brain_enhanced_schema["brain_interpretation"] = brain_interpreted_intent
        brain_enhanced_schema["brain_clarifications_needed"] = brain_clarifications
        brain_enhanced_schema["brain_suggested_questions"] = brain_suggestions
        # Use the merged session schema plus brain insights for LLM context
        response = llm_wrapper(prompt, brain_enhanced_schema)

    return JSONResponse(content={
        "session_id": sid,
        "used_existing_session": used_existing_session,
        "agent_result": agent_result,
        "brain_analysis": brain_analysis,
        "neura_z_response": response
    })

@app.get("/zeta/health")
def health():
    return {"status": "ok", "message": "ZetaCore is running!"}

@app.get("/zeta/sessions")
def list_sessions():
    """List all active session IDs."""
    return {"sessions": list(session_store.keys())}
