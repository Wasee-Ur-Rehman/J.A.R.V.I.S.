# J.A.R.V.I.S: AI-Powered IoT Companion

J.A.R.V.I.S is an advanced IoT desktop assistant that bridges the gap between digital intelligence and the physical environment. By integrating local LLMs with real-time sensor data, J.A.R.V.I.S can monitor environmental conditions, engage in natural conversation, and actuate hardware devices autonomously.

---

## System Architecture

The system employs a modular, event-driven architecture designed for low latency and high scalability:

- **Core Intelligence:** Locally hosted **Gemma 2 (2B)** LLM via Ollama for edge-processing, paired with **Azure Cognitive Services** for high-fidelity speech synthesis and recognition.
- **Backend:** High-performance **FastAPI** server managing the AI pipeline and hardware integration.
- **Communication Layer:** Secure, TLS-encrypted **MQTT** messaging via private EMQX Cloud infrastructure.
- **Hardware Layer:** **ESP32-S3** microcontroller utilizing I2S audio interfaces and standard IoT sensors (DHT11/MQ-2).

---

## Setup Instructions

### 1. Prerequisites

Ensure your development machine has the following:

- **Python 3.10+**
- **Ollama** installed ([ollama.com](https://ollama.com))
- **Azure Account** (Provisioned with Speech Services)
- **EMQX Cloud Account** (Private Serverless Deployment)

### 2. Backend Initialization

1. **Clone and Setup Environment:**

   ```bash
   git clone <repository-url>
   cd jarvis-companion
   python -m venv venv
   # Activate: Windows (venv\Scripts\activate) | Linux/macOS (source venv/bin/activate)
   pip install -r requirements.txt
   ```

2. **Configuration:**
   Create a `.env` file in the root directory with your credentials:

   ```ini
   SPEECH_KEY="<your_azure_key>"
   SPEECH_REGION="<your_azure_region>"
   MQTT_BROKER="<your_emqx_address>"
   MQTT_PORT=8883
   MQTT_USER="<your_username>"
   MQTT_PASS="<your_password>"
   ```

3. **Launch AI Engine:**
   Ensure Ollama is running and the model is loaded:

   ```bash
   ollama pull gemma2:2b
   ollama serve
   ```

4. **Start the API:**
   ```bash
   python main.py
   ```

---

## Hardware & Connectivity

The system uses the following topic convention for all MQTT interactions:

| Scope                   | MQTT Topic Pattern           |
| :---------------------- | :--------------------------- |
| **Telemetry (Sensors)** | `fastnu/companion/sensors/#` |
| **Control (Actuators)** | `fastnu/companion/control/#` |

- **Security:** The ESP32 must implement `WiFiClientSecure` to establish an encrypted handshake with the EMQX broker on port `8883`.
- **Audio API:** The firmware is required to perform an `HTTP POST` request to the backend `/chat` endpoint using `multipart/form-data` with the key `audio_file`.

---

## Testing & Validation

1. **MQTT Connectivity:** Use **MQTT Explorer** to monitor traffic. Publish to `fastnu/companion/sensors/temp` to simulate sensor inputs.
2. **AI Pipeline:** Verify the STT-LLM-TTS pipeline by sending a POST request via Postman to `localhost:8000/chat` with a `.wav` sample.
3. **Dashboard:** Open `index.html` in any browser to verify real-time status updates via WebSockets.

---

## Key Features

- **Context Awareness:** The AI incorporates live environmental data (temperature/gas levels) into its system prompt for context-aware responses.
- **Conversation History:** Implements a sliding window memory buffer (last 10 interactions) for a continuous user experience.
- **Modern HUD:** Features a high-performance, glass-morphism styled dashboard for real-time telemetry and manual override.
