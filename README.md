# ZetaCore: Smart Scheduling Assistant

A modular, conversational scheduling assistant that integrates Google Calendar with the Gemini AI API to provide natural language scheduling capabilities with robust slot-filling, session management, and voice interface options.

## Architecture Overview

ZetaCore is built with a modular architecture designed for clarity, maintainability, and extensibility:

### Core Components

1. **ZetaCore.py** - Main system orchestrator
   - FastAPI backend service that coordinates all other components
   - Manages user sessions and conversation state
   - Implements robust slot-filling for meeting details
   - Ensures schema persistence and consistency

2. **Agent Z (agent_z.py)** - Natural Language Processing Engine
   - Performs entity recognition and intent extraction
   - Creates and maintains JSON schema for meeting details
   - Resolves dates, times and duration references
   - Makes decisions about required actions (fetch availability, schedule meeting)

3. **Neura-Z (neura_z.py)** - LLM Integration Layer
   - **The Brain**: Extracts details from vague queries using LLM
   - **The Tongue**: Generates natural, helpful responses
   - Provides speech-to-text and text-to-speech capabilities
   - Maintains context awareness through schema history

4. **Fetcher (fetcher.py)** - Calendar Availability Handler
   - Interfaces with Google Calendar API
   - Retrieves user's availability for specific dates
   - Formats availability data for presentation

5. **Scheduler (scheduler.py)** - Meeting Creation Manager
   - Creates calendar events based on completed schemas
   - Handles time range parsing and date normalization
   - Ensures appropriate event formatting for Google Calendar

6. **Voice Interface (voice_interface.py)** - Speech Interaction Layer
   - Command-line tool for testing speech capabilities
   - Provides interactive voice assistant mode
   - Demonstrates TTS/STT integration

## Features

- **Natural Language Understanding**: Process conversational requests like "Schedule a meeting with John on Friday"
- **Robust Slot-Filling**: Intelligently collect missing meeting details over multiple turns
- **Session Management**: Maintain conversation context across interactions
- **Calendar Integration**: Check availability and schedule directly to Google Calendar
- **Confirmation Logic**: Get explicit user confirmation before scheduling
- **Schema Normalization**: Ensure consistent date/time formats for reliable processing
- **Speech Interface**: Text-to-speech and speech-to-text capabilities
- **LLM-Enhanced Responses**: Natural, helpful replies using Gemini API
- **Vague Query Resolution**: Extract structured data from ambiguous requests

## Setup Instructions

### Prerequisites

- Python 3.8+
- Google Cloud Platform account
- Google Calendar API enabled
- Gemini API key

### Installation

1. **Clone the repository**:
   ```
   git clone https://github.com/Parallax316/Smart_Scheduler.git
   cd Smart_Scheduler
   ```

2. **Create and activate a virtual environment** (recommended):
   ```
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Unix/MacOS
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```
   pip install -r requirements.txt
   ```

4. **Set up Google Calendar API credentials**:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Google Calendar API
   - Create OAuth 2.0 credentials and download as `credentials.json`
   - Place `credentials.json` in the root directory
   
   For advanced users/deployment:
   - Alternatively, create a service account and download as `service_account.json`
   - Place `service_account.json` in the root directory

5. **Configure Gemini API key**:
   - Get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
   - Create a `.env` file in the root directory with:
     ```
     GOOGLE_GEMINI_API_KEY=your_api_key_here
     ```

### First Run Authentication

The first time you run the application, you'll need to authenticate with Google Calendar:
1. A browser window will open asking you to log in to your Google account
2. Grant the requested permissions
3. The application will store your authentication token for future use

## Running the Application

### FastAPI Backend

Start the ZetaCore backend server:

```
uvicorn ZetaCore:app --reload
```
This will start the FastAPI server on http://localhost:8000 by default.

###  React Frontend
```
cd frontned

npm install  # try running it with force or legacy peers command if it fails)

npm run dev 
```


### Voice Interface

To use the voice interface capabilities:

```
# For text-to-speech
python voice_interface.py --tts --text "Hello, how can I help you schedule a meeting?"

# For speech-to-text (from microphone)
python voice_interface.py --stt

# For interactive voice assistant mode
python voice_interface.py --interactive
```

## API Endpoints

- `/zeta/chat` - Main conversation endpoint
  - POST parameters:
    - `prompt` (string): User message
    - `session_id` (string, optional): Session identifier for conversation continuity

- `/zeta/availability` - Get calendar availability
  - GET parameters:
    - `date` (string, optional): Date to check in ISO format (YYYY-MM-DD)

- `/zeta/schedule` - Schedule a new meeting
  - POST parameters:
    - `schema` (object): Complete meeting details schema

## Integration Guide

### Backend Integration

```python
import requests

# Initialize a session
response = requests.post(
    "http://localhost:8000/zeta/chat",
    json={"prompt": "Schedule a meeting with John tomorrow at 2pm"}
)
data = response.json()
session_id = data["session_id"]

# Continue conversation
response = requests.post(
    "http://localhost:8000/zeta/chat",
    json={"prompt": "Make it for 1 hour", "session_id": session_id}
)
```

### Speech Integration

```python
from neura_z import text_to_speech, speech_to_text, neura_z_respond_with_tts

# Convert text to speech
audio_file = text_to_speech("When would you like to schedule the meeting?")

# Convert speech to text
user_input = speech_to_text()  # Uses microphone by default

# Complete voice interaction
response = neura_z_respond_with_tts(user_input)
```

## Technologies Used

- **FastAPI**: Backend API framework
- **Streamlit**: User interface (optional)
- **Google Calendar API**: Calendar integration
- **Google Gemini API**: LLM for conversation
- **Spacy**: NLP processing
- **gTTS & SpeechRecognition**: Speech capabilities
- **Python-dotenv**: Environment variable management
- **Pytz**: Timezone handling
- **DateParser**: Natural language date parsing

## Troubleshooting

### API Rate Limits
- If you encounter "Resource exhausted" or "Quota exceeded" errors with Gemini API:
  - Check your quota limits at [Google AI Studio](https://ai.google.dev/)
  - Consider upgrading to a paid tier if needed
  - Implement rate limiting in your application

### Calendar Authentication
- If authentication fails:
  - Delete `token.pickle` and try again
  - Ensure `credentials.json` is properly formatted
  - Check that required scopes are enabled

### Audio Issues
- For microphone problems:
  - Ensure PyAudio is properly installed
  - Check microphone permissions
  - Use `--audio` flag with a file path instead of live microphone

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
