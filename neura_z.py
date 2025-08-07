# Neura-Z: LLM-Powered Conversational Agent
# This module acts as the "tongue" of your system, turning structured info (availability, meeting confirmation, user query) into natural, helpful responses.

import google.generativeai as genai
import os
from fetch_availability import get_user_timezone

GOOGLE_GEMINI_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

def neura_z_respond(user_query, availability=None, meeting_confirmation=None, user_timezone=None, current_schema=None):
    """
    Compose a natural, agent-like response as Neura-Z, given the user query and any structured info (availability, meeting confirmation, etc).
    """
    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError("GOOGLE_GEMINI_API_KEY not set in environment.")
    genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
    user_timezone = user_timezone or get_user_timezone()

    # Compose context
    context = f"User's timezone: {user_timezone}.\n"
      # Add schema information to context if available
    if current_schema:
        # Create a more structured and readable format for important scheduling fields
        important_fields = []
        if current_schema.get("date"):
            important_fields.append(f"Date: {current_schema.get('date')}")
        if current_schema.get("time"):
            important_fields.append(f"Time: {current_schema.get('time')}")
        if current_schema.get("duration"):
            important_fields.append(f"Duration: {current_schema.get('duration')}")
        if current_schema.get("event_title"):
            important_fields.append(f"Event: {current_schema.get('event_title')}")
        
        if important_fields:
            context += "Current meeting details:\n- " + "\n- ".join(important_fields) + "\n"
        
        # Also include the full schema for completeness
        schema_info = ", ".join([f"{k}: {v}" for k, v in current_schema.items() if v is not None and k not in ['brain_analysis', 'brain_interpretation', 'brain_clarifications_needed', 'brain_suggested_questions']])
        if schema_info:
            context += f"Additional details: {schema_info}\n"
    
    events_summary = ""
    if availability:
        events = availability.get("events", [])
        if not events:
            events_summary = "You have no events scheduled for this day.\n"
        else:
            events_summary = "Your calendar for this day: "
            for event in events:
                events_summary += f"\n- {event['title']} from {event['start_time']} to {event['end_time']}"
    
    if meeting_confirmation:
        import dateparser
        start_time = meeting_confirmation.get('start', {}).get('dateTime', '')
        try:
            # Parse the dateTime to a more readable format
            parsed_start = dateparser.parse(start_time)
            formatted_date = parsed_start.strftime("%A, %B %d at %I:%M %p")
            
            # Get duration if available
            end_time = meeting_confirmation.get('end', {}).get('dateTime', '')
            duration_text = ""
            if end_time:
                try:
                    parsed_end = dateparser.parse(end_time)
                    duration_mins = int((parsed_end - parsed_start).total_seconds() / 60)
                    duration_text = f" for {duration_mins} minutes"
                except:
                    pass
            
            context += f"\nMEETING SCHEDULED SUCCESSFULLY: {meeting_confirmation.get('summary', 'Meeting')} on {formatted_date}{duration_text} at {meeting_confirmation.get('location', 'N/A')}.\n"
        except:
            # Fallback if parsing fails
            context += f"\nMEETING SCHEDULED SUCCESSFULLY: {meeting_confirmation.get('summary', 'Meeting')} on {start_time} at {meeting_confirmation.get('location', 'N/A')}.\n"    # Get brain insights if available
    brain_interpretation = current_schema.get("brain_interpretation", "") if current_schema else ""
    brain_clarifications = current_schema.get("brain_clarifications_needed", []) if current_schema else []
    brain_suggestions = current_schema.get("brain_suggested_questions", []) if current_schema else []
    
    # Compose explicit guidance based on brain analysis
    brain_guidance = ""
    if brain_interpretation:
        brain_guidance += f"\nYour 'brain' has interpreted the user's intent as: {brain_interpretation}"
    
    if brain_clarifications:
        brain_guidance += f"\nYou still need clarification on: {', '.join(brain_clarifications)}"
    
    if brain_suggestions and not meeting_confirmation:
        brain_guidance += f"\nConsider asking these follow-up questions: {'; '.join(brain_suggestions)}"    # Check if we have all needed information to schedule a meeting
    has_date = current_schema.get("date") is not None if current_schema else False
    has_time = current_schema.get("time") is not None if current_schema else False
    has_event_title = current_schema.get("event_title") is not None if current_schema else False
    has_duration = current_schema.get("duration") is not None if current_schema else False
    has_user_confirmation = current_schema.get("user_confirmation") is True if current_schema else False
    
    # Determine if we have enough info to schedule
    is_ready_for_confirmation = has_date and has_time and (has_event_title or has_duration) and not has_user_confirmation
      # Add this to brain guidance
    confirmation_guidance = ""
    if is_ready_for_confirmation:
        event_title = current_schema.get("event_title", "meeting")
        date_str = current_schema.get("date", "")
        time_str = current_schema.get("time", "")
        duration_str = current_schema.get("duration", "")
        
        confirmation_text = f"Great! I have all the details I need. Should I go ahead and schedule this {event_title} for {date_str} at {time_str}"
        if duration_str:
            confirmation_text += f" for {duration_str}"
        confirmation_text += "?"
        
        confirmation_guidance = f"\nIMPORTANT: You have all the necessary information to schedule this meeting. STOP asking for more details and ASK FOR CONFIRMATION instead using ALL the information available. Example: '{confirmation_text}'"
    
    # Compose system prompt
    system_prompt = f"""
You are Neura-Z, a smart, friendly, and highly capable personal scheduling assistant. Your job is to:
- Understand the user's query and the structured info you receive (calendar availability, meeting confirmations, etc).
- Respond in a natural, helpful, and concise way, as if you are a real human assistant.
- If you have availability info, ALWAYS include a summary of the user's actual events for that day in your answer, even if you need to ask for more details. Summarize the user's schedule, suggest free/busy slots, or use the event info to answer the user's request directly.
- NEVER assume a specific time - if the user doesn't provide a specific time, ASK for it explicitly.
- NEVER schedule a meeting without explicit confirmation - the user must say "yes", "confirm", or similar.
- If a meeting was scheduled, confirm it VERY clearly and definitively with "I've scheduled your meeting" (not "I will" or "I can").
- If the user confirms a meeting (says "yes", "correct", "that's right", etc.) and you have all details needed, reply with "Great! I've scheduled your meeting for [details]".
- If you need more info, ask the user for just what is missing, but always include the day's events in your reply.
- Always refer to yourself as Neura-Z if asked your name.
- Be concise and direct.
- For vague or complex scheduling requests, DO NOT suggest specific times unless the user asks - instead, ask the user what time they prefer.
- For time constraints like "before X" or "after Y", ask for a specific time rather than choosing one automatically.
- CRITICAL: When you have all necessary details (date, time, and either event title or duration), STOP asking for more information and ASK FOR CONFIRMATION to schedule the meeting. ALWAYS include ALL available details in your confirmation request, especially the duration. Example: "Great! I have all the details I need. Should I go ahead and schedule this [event_title] for [date] at [time] for [duration]?"
{brain_guidance}{confirmation_guidance}

Here are examples of how you should respond to different types of requests:

EXAMPLE 1 - Vague scheduling request:
User: "I need to set up a meeting tomorrow."
Assistant: "I'd be happy to help you set up a meeting for tomorrow. Could you please let me know:
1. What time would you prefer?
2. How long should the meeting be?
3. What's the purpose or title of the meeting?

Here's your current schedule for tomorrow:
- Team standup from 10:00 AM to 10:30 AM
- Lunch with client from 12:00 PM to 1:30 PM"

EXAMPLE 2 - Missing time information:
User: "Schedule a doctor's appointment on Friday."
Assistant: "I can help you schedule a doctor's appointment for Friday. What time would you prefer? Also, how long should I block for the appointment?

Here's your current schedule for Friday:
- Morning meeting from 9:00 AM to 10:30 AM
- Weekly review from 2:00 PM to 3:00 PM"

EXAMPLE 3 - Asking for confirmation when all details are available:
User: "Let's do a team meeting tomorrow at 3 PM for 30 minutes."
Assistant: "I have all the details for your team meeting tomorrow at 3:00 PM for 30 minutes. Would you like me to go ahead and schedule this 30-minute meeting now? (Always include ALL details, especially duration, in your confirmation request)"

EXAMPLE 4 - Receiving confirmation:
User: "Yes, please schedule the team meeting we discussed."
Assistant: "Great! I've scheduled your team meeting for tomorrow at 3:00 PM for 30 minutes. Is there anything else you need help with?"

CURRENT CONTEXT:
{context}{events_summary}
USER MESSAGE:
{user_query}
"""
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    response = model.generate_content(system_prompt, generation_config={"max_output_tokens": 1024})
    return response.text

def neura_z_brain(user_query, user_timezone=None, current_schema=None):
    """
    The "brain" of Neura-Z that interprets complex user queries and extracts key meeting parameters.
    This function analyzes ambiguous requests and provides structured information for Agent Z.
    """
    if not GOOGLE_GEMINI_API_KEY:
        raise RuntimeError("GOOGLE_GEMINI_API_KEY not set in environment.")
    genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
    user_timezone = user_timezone or get_user_timezone()
    
    # Prepare context including current schema if available
    context = f"User's timezone: {user_timezone}.\n"
    if current_schema:
        schema_info = ", ".join([f"{k}: {v}" for k, v in current_schema.items() if v is not None])
        if schema_info:
            context += f"Current meeting details: {schema_info}\n"
      # Create the system prompt for the brain
    system_prompt = f"""
You are the "brain" of a scheduling assistant that analyzes user scheduling requests.
Your task is to extract key meeting parameters from user queries and interpret ambiguous requests.
You must determine the true intent and extract essential scheduling information:

1. Extract date information (specific date or relative date)
2. Extract time constraints (before X, after X, between X and Y, specific time)
3. Extract duration information
4. Extract event title or meeting purpose
5. Identify any specific requirements or constraints mentioned
6. Check if the user is confirming a meeting (responding with "yes", "confirm", etc.)

For vague requests, use common sense reasoning to interpret what the user likely means.
Extract as much information as you can, focusing especially on constraints that would help schedule the meeting.

IMPORTANT: Never assume the user wants to schedule a meeting at a specific time unless they explicitly mention the time.
If the user doesn't provide a specific time, you must include "time" in the clarification_needed field.

CRITICAL: Check if the user is confirming a previously discussed meeting. Look for phrases like "yes", "that works", 
"sounds good", "go ahead", "sure", "please do", "ok", "confirm", etc. If present, set user_confirmation to true.

IMPORTANT: When reviewing existing information in the context:
- If the context already has date, time, and either duration or event_title, then NO clarification is needed except confirmation.
- In this case, set "all_details_available" to true and only include "confirmation" in clarification_needed.

Format your response as a JSON object with these fields:
- "interpreted_intent": A brief explanation of what you think the user wants to schedule
- "extracted_date": Any date mentioned, formatted in a way that's easy to process (e.g., "2025-06-20", "Friday", "tomorrow", "next week")
- "extracted_time_constraint": Any time constraints (e.g., "before 6 PM", "after noon", "between 2 PM and 4 PM")
- "extracted_duration": Any duration mentioned (e.g., "45 minutes", "1 hour")
- "extracted_title": Likely meeting title or purpose
- "user_confirmation": Boolean (true/false) indicating if this message is confirming a previously discussed meeting
- "clarification_needed": List of details still needed to schedule (e.g., ["specific time", "meeting title"])
- "suggested_questions": 1-2 natural follow-up questions to ask the user to gather missing details
- "all_details_available": Boolean (true/false) indicating if all required details (date, time, and either duration or title) are available

Focus on extracting meaningful scheduling constraints, especially for vague or complex requests.
Always include missing details in the clarification_needed field and suggest questions to fill these gaps.

CONTEXT:
{context}
USER QUERY:
{user_query}
"""

    # Use the same model as neura_z_respond
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    response = model.generate_content(system_prompt, generation_config={"max_output_tokens": 1024})
    
    # Process the response - should be a JSON object
    response_text = response.text
    
    # Clean up the response if needed to extract the JSON
    import json
    import re
    
    # Extract JSON object from response if surrounded by markdown code blocks or other text
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        response_text = json_match.group(1)
      # Fallback if we still don't have valid JSON
    try:
        brain_analysis = json.loads(response_text)
        
        # Ensure we properly map fields to the expected schema fields
        # Check if we have duration information
        if current_schema and current_schema.get("duration") and not brain_analysis.get("extracted_duration"):
            brain_analysis["extracted_duration"] = current_schema.get("duration")
            print(f"DEBUG: Using duration from existing schema: {current_schema.get('duration')}")
            
        # Log the analysis for debugging
        print(f"DEBUG: Brain analysis result: {brain_analysis}")
    except json.JSONDecodeError:
        # Create a simplified response if parsing fails
        brain_analysis = {
            "interpreted_intent": "schedule a meeting",
            "extracted_date": None,
            "extracted_time_constraint": None,
            "extracted_duration": None,
            "extracted_title": None,
            "user_confirmation": False,
            "clarification_needed": ["date", "time", "duration", "title"],
            "suggested_questions": ["When would you like to schedule this meeting?", "What is the meeting about?"]
        }
    
    return brain_analysis

# TTS and STT helper functions
def text_to_speech(text, output_file="output.mp3"):
    """
    Convert text to speech using Google Text-to-Speech API
    Returns the path to the audio file
    """
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='en')
        tts.save(output_file)
        print(f"TTS: Audio saved to {output_file}")
        return output_file
    except Exception as e:
        print(f"TTS Error: {str(e)}")
        return None

def speech_to_text(audio_file=None):
    """
    Convert speech to text using Google Speech Recognition
    If audio_file is None, it will listen from the microphone
    Returns the transcribed text
    """
    import speech_recognition as sr
    
    recognizer = sr.Recognizer()
    text = ""
    
    try:
        if audio_file:
            # Use audio file
            with sr.AudioFile(audio_file) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
                print(f"STT: Recognized text from file: {text}")
        else:
            # Use microphone
            with sr.Microphone() as source:
                print("STT: Listening... (speak now)")
                audio_data = recognizer.listen(source)
                text = recognizer.recognize_google(audio_data)
                print(f"STT: Recognized text: {text}")
        
        return text
    except sr.UnknownValueError:
        print("STT: Google Speech Recognition could not understand audio")
    except sr.RequestError as e:
        print(f"STT: Could not request results from Google Speech Recognition service; {e}")
    except Exception as e:
        print(f"STT Error: {str(e)}")
    
    return ""

def neura_z_respond_with_tts(user_query, **kwargs):
    """
    Wrapper around neura_z_respond that converts the response to speech
    """
    text_response = neura_z_respond(user_query, **kwargs)
    text_to_speech(text_response)
    return text_response

def neura_z_listen_and_respond(**kwargs):
    """
    Listen for speech input and respond with speech output
    """
    user_query = speech_to_text()
    if user_query:
        return neura_z_respond_with_tts(user_query, **kwargs)
    else:
        return "Sorry, I couldn't understand what you said."
