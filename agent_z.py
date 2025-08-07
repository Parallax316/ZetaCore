# Agent Z: Modular NLP and Availability Handler
# This module handles entity recognition, intent extraction, JSON schema creation, and calendar availability resolution.

import datetime
import pytz
import dateparser
import spacy
import logging
from typing import Dict, Any
import calendar

nlp = spacy.load("en_core_web_sm")
logger = logging.getLogger("agent_z")

# --- Utility Functions ---
def extract_intent_and_slots(message: str, calendar_events: list) -> Dict[str, Any]:
    doc = nlp(message)
    entities = {"duration": None, "event_title": None, "offset": None, "date": None, "time": None}
    
    # Extract entities using spaCy
    for ent in doc.ents:
        if ent.label_ == "TIME":
            if any(term in ent.text.lower() for term in ["minute", "min", "mins", "hour", "hr", "hrs"]):
                entities["duration"] = ent.text
            else:
                entities["time"] = ent.text
        if ent.label_ == "DATE":
            entities["date"] = ent.text
        if ent.label_ == "EVENT":
            entities["event_title"] = ent.text
    
    import re
    
    # Extract duration using regex if not found by spaCy
    if not entities["duration"]:
        duration_match = re.search(r'(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs)', message, re.IGNORECASE)
        if duration_match:
            entities["duration"] = duration_match.group(0)
    
    # Regex fallback for quoted event titles
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", message)
    if quoted and not entities["event_title"]:
        entities["event_title"] = quoted[0][0] or quoted[0][1]
    
    # Enhanced event title extraction - look for noun phrases that might be event titles
    if not entities["event_title"]:
        # Check for common event title patterns
        title_patterns = [
            # Format: [activity] [type]
            r'(\w+\s+(?:class|classes|lesson|lessons|meeting|session|appointment|conference|call))',
            # Format: [type] [activity]
            r'((?:class|classes|lesson|lessons|meeting|session|appointment|conference|call)\s+\w+)',
            # Format: [activity] for X mins/minutes
            r'(\w+(?:\s+\w+)?)\s+for\s+\d+\s*(?:min|mins|minutes)',
            # Piano lessons, yoga class, etc.
            r'((?:piano|yoga|guitar|swimming|martial arts|art|dance|singing|coding|math|science|language|spanish|french|english|mandarin)\s+(?:class|classes|lesson|lessons|session|sessions|meeting|appointment))',
            # "Schedule a [something]" pattern
            r'schedule\s+(?:a|an)\s+(\w+(?:\s+\w+)?)',
            # Common activities
            r'\b(piano|yoga|guitar|swimming|gym|tennis|basketball)\b'
        ]
        
        for pattern in title_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                entities["event_title"] = match.group(1)
                break
                
        # If we still don't have an event title and there's a duration,
        # try to find a noun or noun phrase before the duration
        if not entities["event_title"] and entities["duration"]:
            # Try to find the main activity/subject before the duration
            activity_before_duration = re.search(r'(\w+(?:\s+\w+)?)\s+(?:for)?\s*\d+\s*(?:min|mins|minutes|hour|hours|hr|hrs)', message, re.IGNORECASE)
            if activity_before_duration:
                entities["event_title"] = activity_before_duration.group(1)
    
    # Offset extraction
    offset_match = re.search(r"(a day or two after|a day after|two days after|next day|the day after|\+\d+ day|\+\d+ days)", message, re.IGNORECASE)
    if offset_match:
        entities["offset"] = offset_match.group(0)
          # Check for user confirmation words
    confirmation_words = ["yes", "confirm", "schedule it", "book it", "that works", "sounds good", "go ahead", "please do", "sure", "ok", "okay", "that's right", "correct", "exactly"]
    user_confirmation = any(word in message.lower() for word in confirmation_words)
    
    # Improved intent detection
    schedule_keywords = ["schedule", "find a time", "book", "set up", "arrange", "fix", "move", "reschedule", "change", "shift", "update", "postpone"]
    check_keywords = ["free", "busy", "available", "availability"]
    
    # Check if we have enough details to assume scheduling intent
    has_scheduling_details = (
        (entities["date"] is not None or entities["time"] is not None) and 
        (entities["duration"] is not None or entities["event_title"] is not None)
    )
    
    if any(word in message.lower() for word in schedule_keywords):
        intent = "schedule_meeting"
    elif any(word in message.lower() for word in check_keywords):
        intent = "check_availability"
    elif has_scheduling_details:
        # If message contains date/time AND (duration OR event title), assume scheduling intent
        intent = "schedule_meeting"
    else:
        intent = "unknown"
    
    # If the user is trying to schedule something with a specific purpose (like classes),
    # it's almost certainly a scheduling intent
    if entities["event_title"] is not None and entities["duration"] is not None:
        intent = "schedule_meeting"
    
    # Create the schema
    schema = {
        "intent": intent,
        "duration": entities["duration"],
        "date": entities["date"],
        "time": entities["time"],
        "user_confirmation": user_confirmation
    }
    
    # Add event_title directly to schema to make it more accessible
    if entities["event_title"]:
        schema["event_title"] = entities["event_title"]
    
    # Add relative_reference if both event_title and offset are available
    if entities["event_title"] and entities["offset"]:
        schema["relative_reference"] = {
            "event_title": entities["event_title"],
            "offset": entities["offset"]
        }
    
    return schema

def find_event_date_by_title(title: str, calendar_events: list) -> str:
    for event in calendar_events:
        if title and title.lower() in event['title'].lower():
            return event['date']
    return None

def resolve_date(schema: dict, calendar_events: list, user_timezone: str, now: datetime.datetime) -> datetime.datetime:
    if schema["date"]:
        # Use our new utility function to ensure we always get future dates for weekday references
        resolved_date = parse_future_date(schema["date"], user_timezone, now)
        if resolved_date:
            return resolved_date
    elif schema["relative_reference"] and schema["relative_reference"].get("event_title"):
        anchor_date = find_event_date_by_title(schema["relative_reference"]["event_title"], calendar_events)
        if anchor_date:
            offset = schema["relative_reference"].get("offset")
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
            return anchor_dt + datetime.timedelta(days=days_offset)
    return now

def parse_future_date(date_str, timezone_str="UTC", now=None):
    """
    Parse a date string and always return a future date for weekday references.
    If the parsed date is in the past and the input is a weekday name,
    this will return the next occurrence of that weekday.
    """
    if now is None:
        tz = pytz.timezone(timezone_str)
        now = datetime.datetime.now(tz)
    
    # First attempt standard parsing
    parsed_date = dateparser.parse(date_str, settings={"TIMEZONE": timezone_str, "RETURN_AS_TIMEZONE_AWARE": True})
    
    if parsed_date is None:
        return None
        
    # If parsed date is in the past and input looks like a weekday name, get next occurrence
    if parsed_date.date() < now.date():
        weekdays = [day.lower() for day in calendar.day_name]
        input_lower = date_str.strip().lower()
        
        # Check if input is a weekday name (Monday through Sunday)
        if input_lower in weekdays:
            weekday_num = weekdays.index(input_lower)
            days_ahead = (weekday_num - now.weekday() + 7) % 7
            if days_ahead == 0:
                days_ahead = 7  # If today is the target weekday, get next week
            next_date = now + datetime.timedelta(days=days_ahead)
            # Reset time to midnight to match dateparser's default behavior
            return next_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    return parsed_date

# --- Main Agent Z Handler ---
def agent_z_handler(
    message: str,
    calendar_events: list,
    fetch_availability_fn,  # Should be fetch_availability_structured from fetcher.py
    schedule_meeting_fn,
    call_llm_fn,
    user_timezone: str,
    now: datetime.datetime,
    initial_schema: dict = None
):
    logger.info(f"Agent Z received: {message}")
    logger.info(f"Initial schema: {initial_schema}")
    new_schema = extract_intent_and_slots(message, calendar_events)
    # Merge with initial_schema (session schema)
    schema = dict(initial_schema) if initial_schema else {}
    
    # Check if we have brain insights from the Neura-Z brain
    brain_insights = schema.pop("brain_analysis", {}) if schema else {}
    
    # Incorporate brain insights if available
    if brain_insights:
        logger.info(f"Brain insights received: {brain_insights}")
        # Update schema with brain insights, only if fields aren't already set by extract_intent_and_slots
        for key, value in brain_insights.items():
            if value is not None and (key not in new_schema or new_schema[key] is None):
                new_schema[key] = value
                
        # Handle time constraints specially
        if brain_insights.get("time_constraint") and "before" in brain_insights.get("time_constraint", ""):
            # For "before X" constraints, we should prioritize scheduling earlier
            logger.info(f"Time constraint detected: {brain_insights['time_constraint']}")
            # You could add this to the schema for reference later
            schema["time_constraint"] = brain_insights["time_constraint"]
            
        # Add event context if brain identified a better event title
        if brain_insights.get("event_title") and (not new_schema.get("event_title") or new_schema["event_title"] == "to meet"):
            new_schema["event_title"] = brain_insights["event_title"]
    
    # Properly merge dictionaries with a deep merge for nested dictionaries
    for key, new_value in new_schema.items():
        if new_value is None:
            continue
        
        # Handle nested dictionaries like relative_reference
        if isinstance(new_value, dict) and key in schema and isinstance(schema[key], dict):
            # Deep merge the nested dictionary
            for nested_key, nested_val in new_value.items():
                if nested_val is not None:  # Only update non-None nested values
                    schema[key][nested_key] = nested_val
        else:
            # For non-dict values or new dict keys, just update directly
            # Keep existing intent if the new intent is "unknown"
            if key == "intent" and new_value == "unknown" and schema.get("intent") == "schedule_meeting":
                # Keep existing "schedule_meeting" intent
                logger.info(f"Keeping existing 'schedule_meeting' intent despite new 'unknown' value")
                continue
            else:
                schema[key] = new_value

    # --- Normalize date to explicit ISO string if present ---
    if schema.get("date"):
        normalized_date = parse_future_date(schema["date"], user_timezone, now)
        if normalized_date:
            schema["date"] = normalized_date.date().isoformat()

    # Ensure event_title from relative_reference is also accessible at the top level
    if schema.get("relative_reference") and schema["relative_reference"].get("event_title"):
        if not schema.get("event_title"):
            schema["event_title"] = schema["relative_reference"]["event_title"]

    logger.info(f"Agent Z schema: {schema}")
      # If we have enough details, update the intent to schedule_meeting
    if schema.get("date") and schema.get("time") and (schema.get("duration") or schema.get("event_title")):
        schema["intent"] = "schedule_meeting"
        logger.info(f"Setting intent to 'schedule_meeting' based on available slots")
    
    # PRIORITY 1: Schedule meeting if we have all required details AND user has confirmed
    if (schema.get("intent") == "schedule_meeting" and 
        schema.get("date") and 
        schema.get("time") and 
        (schema.get("duration") or schema.get("event_title")) and 
        schema.get("user_confirmation") == True):
        # Make sure schema has an event_title, even if it's generic
        if not schema.get("event_title"):
            schema["event_title"] = "Meeting"
            
        logger.info(f"Agent Z attempting to schedule with schema: {schema}")
        # Debug logging to help identify why scheduling might not occur
        logger.info(f"Scheduling conditions: intent={schema.get('intent')}, date={schema.get('date')}, time={schema.get('time')}, duration={schema.get('duration')}, event_title={schema.get('event_title')}, user_confirmation={schema.get('user_confirmation')}")
        event = schedule_meeting_fn(schema, user_timezone)
        logger.info(f"Agent Z scheduled event: {event}")
        return {
            "action": "schedule_meeting",
            "schema": schema,
            "event": event
        }
    
    # PRIORITY 2: Show availability if we have a date
    resolved_date = None
    if schema.get("date"):
        resolved_date = dateparser.parse(schema["date"], settings={"TIMEZONE": user_timezone, "RETURN_AS_TIMEZONE_AWARE": True})
    elif schema.get("relative_reference") and schema["relative_reference"].get("event_title"):
        anchor_date = find_event_date_by_title(schema["relative_reference"]["event_title"], calendar_events)
        if anchor_date:
            offset = schema["relative_reference"].get("offset")
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
    
    if resolved_date:
        from fetcher import fetch_availability_structured
        date_str = resolved_date.date().isoformat() if hasattr(resolved_date, 'date') else str(resolved_date)
        availability = fetch_availability_structured(date=date_str, calendar_events=calendar_events)
        logger.info(f"Agent Z availability: {availability}")
        return {
            "action": "show_availability",
            "schema": schema,
            "resolved_date": str(resolved_date),
            "availability": availability
        }
    
    # PRIORITY 3: Not enough info, call LLM for clarification or next step
    logger.info("Agent Z: Not enough info, calling LLM for clarification.")
    llm_response = call_llm_fn(message, schema)
    return {
        "action": "clarify_or_continue",
        "schema": schema,
        "llm_response": llm_response
    }
