# Scheduler: Modular Google Calendar Event Scheduler
# This module schedules events in Google Calendar given structured info (schema) from Agent Z.

import datetime
import pytz
from googleapiclient.discovery import build
from fetch_availability import authenticate, get_user_timezone
from agent_z import parse_future_date

def schedule_event_from_schema(schema, user_timezone=None):
    """
    Schedules an event in Google Calendar using details from Agent Z's schema.
    Expects schema to have: event_title, date, time, duration, and optionally location, description, attendees.
    Handles all time formatting and RFC3339 logic as in fetch_availability.py.
    """
    creds = authenticate()
    service = build('calendar', 'v3', credentials=creds)
    user_timezone = user_timezone or get_user_timezone()

    # Extract details from schema
    title = schema.get('event_title') or schema.get('relative_reference', {}).get('event_title') or 'Meeting'
    date = schema.get('date')
    time = schema.get('time')
    duration = schema.get('duration')
    location = schema.get('location', '')
    description = schema.get('description', '')
    attendees = schema.get('attendees', [])    # Parse start datetime
    start_dt = None
    now = datetime.datetime.now(pytz.timezone(user_timezone))
    if date and time:
        # Pass date and time together to our utility function
        start_dt = parse_future_date(f"{date} {time}", user_timezone, now)
    elif date:
        # Pass just the date
        start_dt = parse_future_date(date, user_timezone, now)
    else:
        # Default to now
        start_dt = now

    # Patch: Handle time ranges like '5 p.m. to 6:00 p.m.'
    if time and (' to ' in time or '-' in time):
        import re
        # Try to extract the first time in the range
        match = re.match(r"([\d:.apmAPM ]+)[\s\-to]+", time)
        if match:
            time = match.group(1).strip()
        else:
            # Fallback: split by 'to' or '-' and take the first part
            time = re.split(r' to |\-', time)[0].strip()

    # Parse duration (e.g., '15 minutes', '1 hour')
    end_dt = start_dt
    if duration:
        import re
        min_match = re.search(r"(\d+)\s*min", duration)
        hr_match = re.search(r"(\d+)\s*hour", duration)
        if min_match:
            end_dt = start_dt + datetime.timedelta(minutes=int(min_match.group(1)))
        elif hr_match:
            end_dt = start_dt + datetime.timedelta(hours=int(hr_match.group(1)))
        else:
            end_dt = start_dt + datetime.timedelta(minutes=30)
    else:
        end_dt = start_dt + datetime.timedelta(minutes=30)

    # Format start and end times for Google Calendar API (RFC3339)
    start_str = start_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    end_str = end_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None).isoformat() + 'Z'

    event_body = {
        'summary': title,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start_str,
            'timeZone': user_timezone,
        },
        'end': {
            'dateTime': end_str,
            'timeZone': user_timezone,
        },
    }
    if attendees:
        event_body['attendees'] = [{'email': email} for email in attendees]
    event = service.events().insert(calendarId='primary', body=event_body).execute()
    return event
