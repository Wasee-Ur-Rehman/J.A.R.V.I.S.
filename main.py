import paho.mqtt.client as mqtt
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
import json
import os
import ollama
import azure.cognitiveservices.speech as speechsdk
import ssl
from dotenv import load_dotenv
import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np
import pygame

pygame.mixer.init()

LISTEN_DURATION_S = 4
LISTEN_SAMPLE_RATE = 16000

load_dotenv()
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
TOPIC_PREFIX = "fastnu/companion"

room_status = {"temperature": 0.0, "humidity": 0.0, "gas": "SAFE"}


# ── MQTT ────────────────────────────────────────────────────────────────────


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT Broker!")
        client.subscribe(f"{TOPIC_PREFIX}/sensors/#")
    else:
        print(f"❌ MQTT Connection failed: rc={rc}")


def on_message(client, userdata, msg):
    global room_status
    topic = msg.topic
    payload = msg.payload.decode("utf-8")

    if topic == f"{TOPIC_PREFIX}/sensors/temp":
        room_status["temperature"] = float(payload)
        print(f"[MQTT] Temp updated: {payload}°C")
    elif topic == f"{TOPIC_PREFIX}/sensors/humidity":
        room_status["humidity"] = float(payload)
        print(f"[MQTT] Humidity updated: {payload}%")
    elif topic == f"{TOPIC_PREFIX}/sensors/gas":
        room_status["gas"] = payload
        print(f"[MQTT] Gas status updated: {payload}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)

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


# ── PIPELINE ─────────────────────────────────────────────────────────────────


def speech_to_text(audio_filepath: str) -> str:
    print("🎤 Sending to Azure STT...")
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY, region=SPEECH_REGION
    )
    audio_config = speechsdk.audio.AudioConfig(filename=audio_filepath)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config, audio_config=audio_config
    )

    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"[STT] Result: {result.text}")
        return result.text
    else:
        print(f"[STT] Failed: {result.reason}")
        return ""


def text_to_speech(text: str, output_filepath: str):
    print("🔊 Generating Azure TTS...")
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY, region=SPEECH_REGION
    )
    speech_config.speech_synthesis_voice_name = "en-US-GuyNeural"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_filepath)
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=audio_config
    )

    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("✅ TTS saved.")
    else:
        print(f"❌ TTS Failed: {result.reason}")


MAX_HISTORY = 10
chat_history = []


def ask_ollama(user_text: str) -> dict:
    global chat_history
    print("🧠 Asking Ollama (Gemma2)...")

    system_prompt = f"""
You are JARVIS, an AI IoT companion.
Current room temperature: {room_status['temperature']}°C.
Current gas status: {room_status['gas']}.

You must respond in ONLY valid JSON format. No markdown, no extra text.
You must wave only when asked, not in future prompts.
Your JSON must have exactly these keys:
"reply": "Your conversational response",
"emotion": "HAPPY", "SAD", "THINKING", or "ALERT",
"fan_command": "ON", "OFF", or "NONE",
"servo_command": "WAVE" or "NONE"
"""

    chat_history.append({"role": "user", "content": user_text})

    if len(chat_history) > MAX_HISTORY:
        chat_history = chat_history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": system_prompt}] + chat_history

    response = ollama.chat(model="gemma2:2b", messages=messages, format="json")

    try:
        data = json.loads(response["message"]["content"])
        print(f"🤖 AI Decision: {data}")
        chat_history.append({"role": "assistant", "content": data["reply"]})
        return data
    except Exception as e:
        print(f"❌ Failed to parse Ollama JSON: {e}")
        if chat_history:
            chat_history.pop()
        return {
            "reply": "I'm sorry, I encountered an error.",
            "emotion": "SAD",
            "fan_command": "NONE",
            "servo_command": "NONE",
        }


def publish_actuators(ai_response: dict):
    if ai_response.get("fan_command") in ["ON", "OFF"]:
        mqtt_client.publish(f"{TOPIC_PREFIX}/control/fan", ai_response["fan_command"])
    if ai_response.get("servo_command") == "WAVE":
        mqtt_client.publish(f"{TOPIC_PREFIX}/control/servo", "WAVE")
    if ai_response.get("emotion"):
        mqtt_client.publish(f"{TOPIC_PREFIX}/display/emotion", ai_response["emotion"])


# ── FASTAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="JARVIS IoT Companion Backend")


@app.get("/")
def read_root():
    return {"status": "Backend is running", "room": room_status}


@app.post("/listen")
async def listen_and_respond():
    """ESP32 hits this endpoint. Laptop records mic, runs full pipeline, plays response."""
    print("🎙️ Recording from laptop mic...")

    audio = sd.rec(
        int(LISTEN_DURATION_S * LISTEN_SAMPLE_RATE),
        samplerate=LISTEN_SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    print("✅ Recording done.")

    input_audio_path = "temp_input.wav"
    wav.write(input_audio_path, LISTEN_SAMPLE_RATE, audio)

    user_text = speech_to_text(input_audio_path)

    if os.path.exists(input_audio_path):
        os.remove(input_audio_path)

    if not user_text:
        return JSONResponse(
            status_code=200, content={"status": "no_speech", "reply": ""}
        )

    ai_response = ask_ollama(user_text)
    publish_actuators(ai_response)

    output_audio_path = "response.wav"
    text_to_speech(ai_response["reply"], output_audio_path)
    pygame.mixer.music.load(output_audio_path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

    return JSONResponse(
        status_code=200, content={"status": "ok", "reply": ai_response["reply"]}
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
