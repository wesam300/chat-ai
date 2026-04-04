# AI Chat Platform
A high-performance AI chat platform using FastAPI and OpenRouter API, featuring a professional UI, image support (Base64), and a robust model fallback system.

## Features
- **FastAPI Backend**: Efficient and modern.
- **Vision Support**: Gemini 2.0 Flash Lite & Qwen-VL integration for images.
- **Fallback System**: Automatic model switching on 429/404 errors.
- **Professional UI**: Responsive chat interface with history.
- **Dockerized**: Ready for Render, Railway, or VPS.

## Setup
1. `pip install -r requirements.txt`
2. Set your `OPENROUTER_API_KEY` environment variable.
3. `uvicorn web_app:app --host 0.0.0.0 --port 8000`

## Deployment
This app is ready for deployment on **Render.com** or **Railway.app** using the provided `Dockerfile`.
