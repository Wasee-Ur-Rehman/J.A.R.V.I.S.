import paho.mqtt.client as mqtt
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
import uvicorn
import json
import os
import shutil
import ollama
import azure.cognitiveservices.speech as speechsdk
import ssl
from dotenv import load_dotenv

# Loading the Environment Variables
load_dotenv()
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
TOPIC_PREFIX = "fastnu/companion"

# Global vars to store the latest sensor readings (updated via MQTT)
room_status = {
    "temperature": 0.0,
    "humidity": 0.0,
    "gas": "SAFE"
}

# MQTT setup
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker!")
        client.subscribe(f"{TOPIC_PREFIX}/sensors/#")
    else:
        print(f"MQTT Connection failed with return code {rc}")

def on_message(client, userdata, msg):
    global room_status
    topic = msg.topic
    payload = msg.payload.decode("utf-8")
    
    if topic == f"{TOPIC_PREFIX}/sensors/temp":
        room_status["temperature"] = float(payload)
        print(f"Temp updated: {payload}°C")
    elif topic == f"{TOPIC_PREFIX}/sensors/humidity":
        room_status["humidity"] = float(payload)
        print(f"Humidity updated: {payload}%")
    elif topic == f"{TOPIC_PREFIX}/sensors/gas":
        room_status["gas"] = payload
        print(f"Gas status updated: {payload}")

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)

# Enable TLS encryption and set username/password for private broker
if MQTT_USER and MQTT_PASS:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set(cert_reqs=ssl.CERT_NONE)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"❌ MQTT Connection failed: {e}")

#  PIPELINE FUNCTIONS

def speech_to_text(audio_filepath: str) -> str:
    """Converts WAV file to text using Azure STT."""
    print("Sending user input to Azure STT...")
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    audio_config = speechsdk.audio.AudioConfig(filename=audio_filepath)
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    
    result = speech_recognizer.recognize_once_async().get()
    
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"STT Result: {result.text}")
        return result.text
    else:
        print(f"STT Failed: {result.reason}")
        return ""

def text_to_speech(text: str, output_filepath: str):
    """Converts text to WAV file using Azure TTS."""
    print("Generating Azure TTS...")
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    # Using a friendly voice
    speech_config.speech_synthesis_voice_name = "en-US-GuyNeural" 
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_filepath)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    
    result = speech_synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("✅ TTS Audio saved successfully.")
    else:
        print(f"❌ TTS Failed: {result.reason}")

MAX_HISTORY = 10  # Keep the last 10 messages to save laptop memory
chat_history = [] # This list will store the conversation

def ask_ollama(user_text: str) -> dict:
    global chat_history
    print("🧠 Asking Ollama (Gemma2) with history...")
    
    # 1. The System Prompt (Updates every time with live sensors)
    system_prompt = f"""
    You are JARVIS, an AI IoT companion.
    Current room temperature: {room_status['temperature']}°C.
    Current gas status: {room_status['gas']}.
    
    You must respond in ONLY valid JSON format. Do not add markdown or outside text.
    Your JSON must have exactly these keys:
    "reply": "Your conversational response",
    "emotion": "HAPPY", "SAD", "THINKING", or "ALERT",
    "fan_command": "ON", "OFF", or "NONE",
    "servo_command": "WAVE" or "NONE"
    """

    # 2. Add the new user message to our history list
    chat_history.append({"role": "user", "content": user_text})
    
    # 3. Trim the history if it gets too long (prevents Ollama from crashing)
    if len(chat_history) > MAX_HISTORY:
        chat_history = chat_history[-MAX_HISTORY:]

    # 4. Combine the system prompt + chat history
    messages = [{"role": "system", "content": system_prompt}] + chat_history

    # 5. Send to Ollama
    response = ollama.chat(
        model='gemma2:2b',
        messages=messages,
        format='json'
    )
    
    try:
        data = json.loads(response['message']['content'])
        print(f"🤖 AI Decision: {data}")
        
        # 6. Save the AI's reply to history so it remembers what it just said
        chat_history.append({"role": "assistant", "content": data["reply"]})
        
        return data
        
    except Exception as e:
        print(f"❌ Failed to parse Ollama JSON: {e}")
        # If it fails, remove the last user message so history doesn't break
        if chat_history: chat_history.pop() 
        return {"reply": "I'm sorry, I encountered an error.", "emotion": "SAD", "fan_command": "NONE", "servo_command": "NONE"}

# --- 4. FASTAPI ROUTES ---
app = FastAPI(title="IoT Companion Backend")

@app.get("/")
def read_root():
    return {"status": "Backend is running", "room": room_status}

@app.post("/chat")
async def process_audio(audio_file: UploadFile = File(...)):
    # 1. Save incoming audio from ESP32
    input_audio_path = "temp_input.wav"
    with open(input_audio_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)
    
    # 2. Azure Speech-to-Text
    user_text = speech_to_text(input_audio_path)
    if not user_text:
        return {"error": "Could not understand audio."}

    # 3. Ollama (Gemma2) LLM Processing
    ai_response = ask_ollama(user_text)

    # 4. Trigger MQTT Actuators
    if ai_response.get("fan_command") in ["ON", "OFF"]:
        mqtt_client.publish(f"{TOPIC_PREFIX}/control/fan", ai_response["fan_command"])
    
    if ai_response.get("servo_command") == "WAVE":
        mqtt_client.publish(f"{TOPIC_PREFIX}/control/servo", "WAVE")
        
    if ai_response.get("emotion"):
        mqtt_client.publish(f"{TOPIC_PREFIX}/display/emotion", ai_response["emotion"])

    # 5. Azure Text-to-Speech
    output_audio_path = "response.wav"
    text_to_speech(ai_response["reply"], output_audio_path)

    # Clean up input file
    if os.path.exists(input_audio_path):
        os.remove(input_audio_path)

    # 6. Return the Audio File directly back to ESP32!
    return FileResponse(output_audio_path, media_type="audio/wav", filename="response.wav")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)