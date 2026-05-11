# AI-Powered IoT Companion (J.A.R.V.I.S)

This project is an AI-powered desktop assistant that combines real-world IoT sensing (temperature/gas) with conversational AI to control physical actuators (fan/servo).

## Architecture

- **Backend:** FastAPI (Python)
- **AI Brain:** Gemma2 (2b/9b) via Ollama + Azure Speech Services (STT/TTS)
- **Communication:** MQTT (EMQX Private Broker)
- **Hardware:** ESP32, DHT11, Fan, Servo, Microphone/Speaker.

## Setup Instructions

### 1. Prerequisites

- **Python 3.10+**
- **Ollama** installed ([ollama.com](https://ollama.com))
- **Azure Account** (For Speech Services)
- **EMQX Cloud Account** (For MQTT)

### 2. Backend Setup

1. **Clone the repo** and create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Setup environment variables:** Create a `.env` file in the root:
   ```ini
   SPEECH_KEY="your_azure_key"
   SPEECH_REGION="your_azure_region"
   MQTT_BROKER="your_emqx_broker_url"
   MQTT_PORT=8883
   MQTT_USER="your_username"
   MQTT_PASS="your_password"
   ```
3. **Run Ollama:** Ensure Gemma2 is pulled:
   ```bash
   ollama pull gemma2:2b
   ollama serve
   ```
4. ** Activate the venv and Start Backend:**
   ```bash
   venv\Scripts\activate
   python main.py
   ```

### 3. Hardware (ESP32) Integration

- **Topic Convention:**
  - Sensors: `fastnu/companion/sensors/#`
  - Control: `fastnu/companion/control/#`
- **Authentication:** Use `WiFiClientSecure` to connect to port `8883` on your EMQX broker using the provided credentials.
- **Audio Pipeline:** ESP32 must send a `POST` request to `{SERVER_IP}:8000/chat` with a `multipart/form-data` file field named `audio_file`.

### 4. Testing

- **MQTT:** Use **MQTT Explorer** to publish values to `fastnu/companion/sensors/temp`.
- **API:** Use Postman/cURL to send a `.wav` file to `/chat` and receive the AI's audio response.
