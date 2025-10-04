# 🌤️ WeatherChat — AI Travel & Weather Companion

**WeatherChat** is an interactive, intelligent chatbot that combines **real-time weather data**, **speech recognition**, and **LLM-powered travel suggestions** into one seamless web experience.  
It provides travel ideas, recommendations, and images of attractions based on your location and current weather conditions.

---

## 🚀 Features

- 🧠 **LLM Integration (via OpenRouter + DeepSeek)**
  - Context-aware travel recommendations using `deepseek/deepseek-chat-v3.1:free`
  - Streaming response (like ChatGPT)
  
- 🎙️ **Speech-to-Text (STT)**  
  - Voice input via **Deepgram API**  
  - Supports **English**, **Japanese**, and **Auto-detect**

- 🌦️ **Weather API Integration**  
  - Real-time weather fetched from **Open-Meteo**  
  - Automatically adjusts background gradient and theme based on conditions (sunny, rainy, cloudy, etc.)

- 📸 **Image Retrieval (Unsplash API)**  
  - Fetches and displays real images of places mentioned in LLM responses

- 💬 **Chat Interface (Frontend)**  
  - Clean ChatGPT-style interface with animated message bubbles  
  - Smooth background transitions based on weather  
  - Toast notifications for actions (recording, transcribing, generating)  
  - Persistent chat via **localStorage**  
  - “Clear Chat” button for starting fresh conversations  

- 🗺️ **Location Detection**
  - Detects your city automatically using your browser’s location (via Nominatim API)

- 🔒 **User Authentication (WIP)**
  - Planned login/register system for storing personalized chat history

- ⚡ **Backend: Flask**
  - Handles LLM, STT, and Weather API integration  
  - Supports both `/api/process` and `/api/stream_process` endpoints  
  - Ready for deployment (can run locally or on cloud)

---

## 🧩 Tech Stack

| Layer | Technology |
|-------|-------------|
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) |
| **Backend** | Python (Flask) |
| **AI Model** | DeepSeek Chat via OpenRouter |
| **Speech Recognition** | Deepgram API |
| **Weather Data** | Open-Meteo API |
| **Image Search** | Unsplash API |
| **Location Detection** | Nominatim (OpenStreetMap) |
| **Persistence** | Browser Local Storage |
| **Future DB (for login)** | SQLite / Firebase (planned) |

---

## 🧠 Project Workflow

1. User inputs text (or speaks) their query.  
2. Deepgram converts speech → text (STT).  
3. The system extracts the **city** from the query using the LLM.  
4. Open-Meteo API fetches weather & temperature for that city.  
5. Weather data is provided back to the LLM for context-aware suggestions.  
6. Unsplash API fetches images for locations mentioned by the LLM.  
7. The frontend displays a streaming chat response + images dynamically.  
8. Background color transitions based on weather (sunny → yellow, rainy → blue, cloudy → grey).

---


## ⚙️ Setup Instructions

### 1️⃣ Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/weatherchat.git
cd weatherchat
