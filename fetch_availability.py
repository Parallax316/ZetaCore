# Google Calendar Availability Fetcher
#
# This script fetches your availability from Google Calendar using the Google Calendar API.
#
# Prerequisites:
# 1. Install required packages: pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
# 2. Download OAuth 2.0 credentials from Google Cloud Console and save as 'credentials.json' in the same directory as this script.
#
# Usage:
#   python fetch_availability.py

import datetime
import os.path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import json
import requests
import pytz
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.responses import JSONResponse
import dateparser
import google.generativeai as genai
from dotenv import load_dotenv
import spacy
import logging
from agent_z import agent_z_handler

# If modifying these SCOPES, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/calendar']

load_dotenv()
GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

nlp = spacy.load("en_core_web_sm")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart_scheduler")


def authenticate():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds


def get_user_timezone():
    """Get the user's timezone using IP geolocation."""
    try:
        response = requests.get('http://ip-api.com/json/')
        data = response.json()
        return data.get('timezone', 'UTC')
    except Exception:
        return 'UTC'


app = FastAPI()

@app.get("/availability")
def availability_endpoint(
    start: str = Query(None, description="Start date/time in ISO format (e.g. 2025-06-19T00:00:00)", alias="start"),
    end: str = Query(None, description="End date/time in ISO format (e.g. 2025-06-20T00:00:00)", alias="end")
):
    data = fetch_availability(return_json=True, start=start, end=end)
    return JSONResponse(content=data)

def fetch_availability(return_json=False, start=None, end=None):
    creds = authenticate()
    service = build('calendar', 'v3', credentials=creds)
    
    # Set the time range for availability
    if start is None:
        now = datetime.datetime.utcnow()
    else:
        now = datetime.datetime.fromisoformat(start)
    
    if end is None:
        end_time = now + datetime.timedelta(days=1)
    else:
        end_time = datetime.datetime.fromisoformat(end)
    
    # Ensure proper RFC3339 format with Z suffix (no +00:00 with Z)
    # Remove any timezone info before adding Z
    now_str = now.replace(tzinfo=None).isoformat() + 'Z'
    end_str = end_time.replace(tzinfo=None).isoformat() + 'Z'
    
    # Call the Calendar API
    events_result = service.events().list(
        calendarId='primary', 
        timeMin=now_str, 
        timeMax=end_str,
        singleEvents=True, 
        orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])
    user_timezone = get_user_timezone()
    tz = pytz.timezone(user_timezone)
    output = []
    
    for event in events:
        start_utc = event['start'].get('dateTime', event['start'].get('date'))
        end_utc = event['end'].get('dateTime', event['end'].get('date'))
        
        try:
            # Handle RFC3339 format correctly - if Z is present, replace with +00:00 for fromisoformat
            if 'Z' in start_utc:
                start_utc = start_utc.replace('Z', '+00:00')
            if 'Z' in end_utc:
                end_utc = end_utc.replace('Z', '+00:00')
            
            start_dt = datetime.datetime.fromisoformat(start_utc).astimezone(tz)
            end_dt = datetime.datetime.fromisoformat(end_utc).astimezone(tz)
            date = start_dt.date().isoformat()
            start_time = start_dt.time().isoformat(timespec='minutes')
            end_time = end_dt.time().isoformat(timespec='minutes')
        except Exception as e:
            print(f"Error parsing event datetime: {e}")
            date = start_utc
            start_time = start_utc
            end_time = end_utc
        output.append({
            'title': event.get('summary', 'No Title'),
            'date': date,
            'start_time': start_time,
            'end_time': end_time,
            'location': event.get('location', ''),
        })
    result = {"timezone": user_timezone, "events": output}
    if return_json:
        return result
    print(json.dumps(result, indent=2))

@app.post("/llm")
def llm_endpoint(prompt: str = Body(..., embed=True)):
    logger.info(f"User query: {prompt}")
    # Fetch all events for the next 30 days for event/entity search
    from datetime import datetime, timedelta
    user_timezone = get_user_timezone() if callable(get_user_timezone) else "UTC"
    now = datetime.now(pytz.timezone(user_timezone))
    calendar_events = fetch_availability(return_json=True, start=now.isoformat()+"Z", end=(now+timedelta(days=30)).isoformat()+"Z")["events"]
    # Extract intent and slots
    schema = extract_intent_and_slots(prompt, calendar_events)
    logger.info(f"Extracted schema: {json.dumps(schema, indent=2)}")
    # Always try to resolve date and fetch availability if date is present
    resolved_date = None
    availability_info = None
    if schema["date"]:
        import dateparser
        resolved_date = dateparser.parse(schema["date"], settings={"TIMEZONE": user_timezone, "RETURN_AS_TIMEZONE_AWARE": True})
    elif schema["relative_reference"] and schema["relative_reference"]["event_title"]:
        anchor_date = find_event_date_by_title(schema["relative_reference"]["event_title"], calendar_events)
        if anchor_date:
            offset = schema["relative_reference"].get("offset")
            days_offset = 0
            if offset:
                import re
                match = re.search(r"(\\d+)", offset)
                if match:
                    days_offset = int(match.group(1))
                elif "two" in offset:
                    days_offset = 2
                else:
                    days_offset = 1
            from datetime import datetime as dt
            anchor_dt = dt.strptime(anchor_date, "%Y-%m-%d")
            resolved_date = anchor_dt + timedelta(days=days_offset)
    # Fallback: today and tomorrow
    if not resolved_date:
        resolved_date = now
        logger.info("No date found, using fallback: today and tomorrow.")
    # Fetch availability for resolved date
    start_dt = resolved_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    start_str = start_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
    end_str = end_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
    availability = fetch_availability(return_json=True, start=start_str, end=end_str)
    logger.info(f"Availability for {resolved_date.date()}: {json.dumps(availability, indent=2)}")
    # Build LLM prompt
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%H:%M")
    datetime_context = (
        f"Today is {date_str}. The current time is {time_str}. The user's timezone is {user_timezone}.\n"
    )
    events_desc = ""
    if availability.get("events"):
        events = availability["events"]
        if not events:
            events_desc = "You have no events scheduled for this day."
        else:
            events_desc = "You have the following events:\n"
            for event in events:
                events_desc += f"- {event['title']} from {event['start_time']} to {event['end_time']}\n"
    availability_section = f"\nCALENDAR AVAILABILITY FOR {resolved_date.date()}:\n{events_desc}\n"
    # Compose system prompt
    system_prompt = f"""
You are a smart scheduling assistant. You will always receive the user's latest message, the current date/time, and a summary of the user's calendar availability for today and the next day (or for a specific date if the user query references one).
- If the user's query is about scheduling, rescheduling, or checking availability, use the provided calendar info to answer or ask for missing details.
- If the user's query is unrelated to scheduling, you may ignore the calendar info.
- If the calendar info is for today/tomorrow only (fallback), let the user know and ask for more details if needed.
- If the calendar info is for a specific date or event, use it to suggest free/busy slots or confirm the user's intent.
Always respond naturally, referencing the calendar info only if it helps answer the user's request.
CURRENT CONTEXT:
{datetime_context}{availability_section}
USER MESSAGE:
{prompt}
"""
    logger.info(f"LLM system prompt: {system_prompt}")
    # Call LLM
    response = run_llm(system_prompt)
    logger.info(f"LLM response: {response}")
    # Only return Neura-Z's response (as 'neura_z_response')
    return {"neura_z_response": response, "schema": schema, "availability": availability}

def extract_event_title_from_message(message, calendar_events):
    # Try to extract quoted event titles or known event names from the message
    import re
    # Look for single or double quoted strings
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", message)
    candidates = [q[0] or q[1] for q in quoted if q[0] or q[1]]
    # Also try to match event titles by substring
    for event in calendar_events:
        for word in message.split():
            if word.lower() in event['title'].lower() and word.lower() not in candidates:
                candidates.append(event['title'])
    # Return the first match if any
    return candidates[0] if candidates else None

def find_event_date_by_title(title, calendar_events):
    for event in calendar_events:
        if title.lower() in event['title'].lower():
            return event['date']
    return None

def run_llm(prompt, model="gemini-1.5-flash-latest", max_tokens=2048):
    user_timezone = get_user_timezone() if callable(get_user_timezone) else "UTC"
    import pytz
    from datetime import datetime, timedelta
    now = datetime.now(pytz.timezone(user_timezone))
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%H:%M")
    datetime_context = (
        f"Today is {date_str}. The current time is {time_str}. The user's timezone is {user_timezone}.\n"
    )
    # Fetch all events for the next 30 days for event title search
    calendar_events = fetch_availability(return_json=True, start=now.isoformat()+"Z", end=(now+timedelta(days=30)).isoformat()+"Z")['events']
    # Try to extract event title from prompt
    event_title = extract_event_title_from_message(prompt, calendar_events)
    anchor_date = None
    anchor_info = ""
    if event_title:
        anchor_date = find_event_date_by_title(event_title, calendar_events)
        if anchor_date:
            anchor_info = f"\nNOTE: The user's message refers to an event titled '{event_title}', which occurs on {anchor_date}.\n"
    # Pre-parse relative dates in prompt, using anchor_date if found
    import dateparser
    resolved_date = None
    if anchor_date:
        # Try to parse relative to anchor_date
        resolved_date = dateparser.parse(prompt, settings={"TIMEZONE": user_timezone, "RELATIVE_BASE": datetime.strptime(anchor_date, "%Y-%m-%d"), "RETURN_AS_TIMEZONE_AWARE": True})
    if not resolved_date:
        resolved_date = dateparser.parse(prompt, settings={"TIMEZONE": user_timezone, "RETURN_AS_TIMEZONE_AWARE": True})
    resolved_date_str = None
    availability_section = ""
    if resolved_date:
        resolved_date_str = resolved_date.strftime("%Y-%m-%d")
        # Fetch availability for the resolved date
        start_dt = resolved_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=1)
        start_str = start_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
        end_str = end_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
        availability = fetch_availability(return_json=True, start=start_str, end=end_str)
        events_desc = ""
        if availability.get("events"):
            events = availability["events"]
            if not events:
                events_desc = "You have no events scheduled for this day."
            else:
                events_desc = "You have the following events:\n"
                for event in events:
                    events_desc += f"- {event['title']} from {event['start_time']} to {event['end_time']}\n"
        availability_section = f"\nCALENDAR AVAILABILITY FOR {resolved_date_str}:\n{events_desc}\n"
    # Add resolved date context if found
    resolved_date_section = ""
    if resolved_date_str:
        resolved_date_section = f"\nNOTE: The user's message contains a relative date/time expression. Using dateparser with timezone '{user_timezone}', it resolves to: {resolved_date_str}. Please use this resolved date in your reasoning and confirm with the user if needed.\n"
    full_prompt = f"{datetime_context}{anchor_info}{availability_section}{resolved_date_section}{prompt}"
    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError("GOOGLE_GEMINI_API_KEY not set in environment.")
    genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
    try:
        model_obj = genai.GenerativeModel(model)
        response = model_obj.generate_content(full_prompt, generation_config={"max_output_tokens": max_tokens})
        return response.text
    except Exception as e:
        return f"Gemini API error: {e}"

def parse_natural_time(text, user_timezone=None):
    """Parse natural language time expressions to ISO format using user's timezone."""
    settings = {'TIMEZONE': user_timezone or 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}
    dt = dateparser.parse(text, settings=settings)
    if dt:
        # Format to ISO format and append Z for UTC (RFC3339 format)
        return dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
    return None

@app.post("/llm_availability")
def llm_availability_endpoint(
    query: str = Body(..., embed=True)
):
    user_timezone = get_user_timezone()
    # Try to extract time expressions from the query
    # For demo, assume the first time-like phrase is the target
    import re
    time_phrases = re.findall(r'(after [^,.;!?]+|before [^,.;!?]+|tomorrow[^,.;!?]*|today[^,.;!?]*|next [^,.;!?]+|\d{1,2} ?(am|pm))', query, re.IGNORECASE)
    if time_phrases:
        # Use the first match for now
        time_phrase = time_phrases[0][0]
        # Decide if it's a 'start' or 'end' query
        if 'after' in time_phrase.lower():
            start = parse_natural_time(time_phrase, user_timezone)
            end = None
        elif 'before' in time_phrase.lower():
            start = None
            end = parse_natural_time(time_phrase, user_timezone)
        else:
            start = parse_natural_time(time_phrase, user_timezone)
            end = None
    else:
        start = None
        end = None
    # Call the availability API
    data = fetch_availability(return_json=True, start=start, end=end)
    # Compose a smart answer
    if not data['events']:
        answer = f"You are free during that time!"
    else:
        answer = f"You have the following events during that time: "
        for event in data['events']:
            answer += f"\n- {event['title']} on {event['date']} from {event['start_time']} to {event['end_time']}"
    return {"answer": answer, "raw": data}

@app.post("/schedule_meeting")
def schedule_meeting(
    title: str = Body(..., embed=True),
    start: str = Body(..., embed=True),
    end: str = Body(..., embed=True),
    location: str = Body('', embed=True),
    description: str = Body('', embed=True),
    attendees: list = Body(default=None, embed=True)
):
    try:
        event = create_event(title, start, end, location, description, attendees)
        return {"status": "success", "event": event}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def create_event(title, start, end, location='', description='', attendees=None):
    creds = authenticate()
    service = build('calendar', 'v3', credentials=creds)
    
    # Format start and end times correctly for Google Calendar API - RFC3339 format
    try:
        # If time string has +00:00, convert to Z format
        if '+00:00' in start:
            start = start.replace('+00:00', 'Z')
        # If it doesn't end with Z, add it
        elif not start.endswith('Z'):
            # Remove any timezone info first to avoid duplication
            start_dt = datetime.datetime.fromisoformat(start.replace('Z', '')).replace(tzinfo=None)
            start = start_dt.isoformat() + 'Z'
            
        # Same for end time
        if '+00:00' in end:
            end = end.replace('+00:00', 'Z')
        elif not end.endswith('Z'):
            end_dt = datetime.datetime.fromisoformat(end.replace('Z', '')).replace(tzinfo=None)
            end = end_dt.isoformat() + 'Z'
    except Exception as e:
        print(f"Error formatting event times: {e}")
    
    event_body = {
        'summary': title,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start,
            'timeZone': get_user_timezone(),
        },
        'end': {
            'dateTime': end,
            'timeZone': get_user_timezone(),
        },
    }
    if attendees:
        event_body['attendees'] = [{'email': email} for email in attendees]
    event = service.events().insert(calendarId='primary', body=event_body).execute()
    return event

def extract_intent_and_slots(message, calendar_events):
    doc = nlp(message)
    entities = {"duration": None, "event_title": None, "offset": None, "date": None, "time": None}
    # spaCy NER
    for ent in doc.ents:
        if ent.label_ == "TIME" and "minute" in ent.text:
            entities["duration"] = ent.text
        if ent.label_ == "DATE":
            entities["date"] = ent.text
        if ent.label_ == "TIME" and "minute" not in ent.text:
            entities["time"] = ent.text
        if ent.label_ == "EVENT":
            entities["event_title"] = ent.text
    # Regex fallback for quoted event titles
    import re
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", message)
    if quoted and not entities["event_title"]:
        entities["event_title"] = quoted[0][0] or quoted[0][1]
    # Offset extraction
    offset_match = re.search(r"(a day or two after|a day after|two days after|next day|the day after|\\+\\d+ day|\\+\\d+ days)", message, re.IGNORECASE)
    if offset_match:
        entities["offset"] = offset_match.group(0)
    # Improved intent detection
    schedule_keywords = ["schedule", "find a time", "book", "set up", "arrange", "fix", "move", "reschedule", "change", "shift", "update", "postpone"]
    check_keywords = ["free", "busy", "available", "availability"]
    if any(word in message.lower() for word in schedule_keywords):
        intent = "schedule_meeting"
    elif any(word in message.lower() for word in check_keywords):
        intent = "check_availability"
    else:
        intent = "unknown"
    return {
        "intent": intent,
        "duration": entities["duration"],
        "relative_reference": {
            "event_title": entities["event_title"],
            "offset": entities["offset"]
        } if entities["event_title"] and entities["offset"] else None,
        "date": entities["date"],
        "time": entities["time"]
    }

@app.post("/chat")
def chat_endpoint(prompt: str = Body(..., embed=True)):
    # This endpoint mirrors /llm for main app integration
    return llm_endpoint(prompt)

@app.post("/fetch")
def fetch_agent_z(
    prompt: str = Body(..., embed=True)
):
    from datetime import datetime, timedelta
    user_timezone = get_user_timezone() if callable(get_user_timezone) else "UTC"
    now = datetime.now(pytz.timezone(user_timezone))
    calendar_events = fetch_availability(return_json=True, start=now.isoformat()+"Z", end=(now+timedelta(days=30)).isoformat()+"Z")["events"]
    result = agent_z_handler(prompt, calendar_events, fetch_availability, user_timezone, now)
    return result

if __name__ == '__main__':
    fetch_availability()
