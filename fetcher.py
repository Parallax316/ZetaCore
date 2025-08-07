# Fetcher: Modular Google Calendar Availability Fetcher
# This module fetches availability from Google Calendar given structured info (date, event title, offset, etc.)

import datetime
import pytz
from googleapiclient.discovery import build
from fetch_availability import authenticate, get_user_timezone

def fetch_availability_structured(date=None, event_title=None, offset=None, calendar_events=None, days_range=1):
    """
    Fetches availability from Google Calendar based on date or event title + offset.
    All time conversion and RFC3339 logic matches fetch_availability.py.
    """
    creds = authenticate()
    service = build('calendar', 'v3', credentials=creds)
    user_timezone = get_user_timezone()
    tz = pytz.timezone(user_timezone)

    # Resolve date if event_title and offset are provided
    if event_title and calendar_events:
        anchor_date = None
        for event in calendar_events:
            if event_title.lower() in event['title'].lower():
                anchor_date = event['date']
                break
        if anchor_date and offset:
            import re
            days_offset = 1
            match = re.search(r"(\d+)", offset)
            if match:
                days_offset = int(match.group(1))
            elif "two" in offset:
                days_offset = 2
            anchor_dt = datetime.datetime.strptime(anchor_date, "%Y-%m-%d")
            date = (anchor_dt + datetime.timedelta(days=days_offset)).date().isoformat()

    # Default to today if no date
    if not date:
        now = datetime.datetime.now(tz)
        date = now.date().isoformat()

    # Set start and end times for the day
    start_dt = datetime.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz, hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + datetime.timedelta(days=days_range)
    start_str = start_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'
    end_str = end_dt.astimezone(pytz.UTC).replace(tzinfo=None).isoformat() + 'Z'

    # Fetch events
    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_str,
        timeMax=end_str,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    output = []
    for event in events:
        start_utc = event['start'].get('dateTime', event['start'].get('date'))
        end_utc = event['end'].get('dateTime', event['end'].get('date'))
        try:
            if 'Z' in start_utc:
                start_utc = start_utc.replace('Z', '+00:00')
            if 'Z' in end_utc:
                end_utc = end_utc.replace('Z', '+00:00')
            start_dt = datetime.datetime.fromisoformat(start_utc).astimezone(tz)
            end_dt = datetime.datetime.fromisoformat(end_utc).astimezone(tz)
            date_str = start_dt.date().isoformat()
            start_time = start_dt.time().isoformat(timespec='minutes')
            end_time = end_dt.time().isoformat(timespec='minutes')
        except Exception as e:
            date_str = start_utc
            start_time = start_utc
            end_time = end_utc
        output.append({
            'title': event.get('summary', 'No Title'),
            'date': date_str,
            'start_time': start_time,
            'end_time': end_time,
            'location': event.get('location', ''),
        })
    return {"timezone": user_timezone, "events": output}
