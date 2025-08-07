#!/usr/bin/env python
# Voice Interface for Neura-Z
# This provides a simple command-line interface to test the TTS and STT features

import os
import sys
import argparse
from neura_z import text_to_speech, speech_to_text, neura_z_respond, neura_z_respond_with_tts, neura_z_listen_and_respond
from fetch_availability import get_user_timezone

def main():
    parser = argparse.ArgumentParser(description='Voice Interface for Neura-Z')
    parser.add_argument('--tts', action='store_true', help='Convert text to speech')
    parser.add_argument('--stt', action='store_true', help='Convert speech to text')
    parser.add_argument('--text', type=str, help='Text to convert to speech')
    parser.add_argument('--audio', type=str, help='Audio file to convert to text')
    parser.add_argument('--interactive', action='store_true', help='Interactive voice assistant mode')
    
    args = parser.parse_args()
    
    # Check if we have the required API key
    api_key = os.getenv("GOOGLE_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GOOGLE_GEMINI_API_KEY not set. Please set this environment variable.")
        sys.exit(1)
        
    # Run the appropriate function based on arguments
    if args.tts and args.text:
        # Text-to-Speech
        output_file = text_to_speech(args.text)
        print(f"Audio saved to {output_file}")
        
    elif args.stt:
        # Speech-to-Text
        if args.audio:
            # From file
            text = speech_to_text(args.audio)
            print(f"Transcribed text: {text}")
        else:
            # From microphone
            print("Listening... (speak now)")
            text = speech_to_text()
            print(f"Transcribed text: {text}")
            
    elif args.interactive:
        # Full interactive assistant
        print("Starting interactive voice assistant.")
        print("Speak to Neura-Z. Say 'quit' or 'exit' to end the session.")
        
        while True:
            print("\nListening... (speak now)")
            user_query = speech_to_text()
            
            if not user_query:
                print("I couldn't understand what you said. Please try again.")
                continue
                
            print(f"You said: {user_query}")
            
            if user_query.lower() in ["quit", "exit", "stop", "bye"]:
                print("Goodbye!")
                break
                
            # Get response from Neura-Z
            response = neura_z_respond(user_query, user_timezone=get_user_timezone())
            print(f"Neura-Z: {response}")
            
            # Convert response to speech
            text_to_speech(response)
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
