# Super Advanced Telegram AI Bot 🚀

Production-grade Telegram AI Chatbot menggunakan Python, `python-telegram-bot` v20+ (Async), dan HuggingFace Inference API (Llama-3).

## Fitur Utama
- **Persistent Memory**: Menggunakan SQLite (aiosqlite) dengan context trimming.
- **Streaming Response**: Merender balasan secara bertahap (chunk) seperti ChatGPT.
- **Robustness**: Dilengkapi retry mechanism (exponential backoff), rate limiter, dan timeout handling.
- **Security Hardened**: Token masking pada logger, validasi input, pencegahan DoS (max tokens limit).
- **Health Check**: Endpoint web ringan (FastAPI) untuk keperluan cloud deployment ping.

## Cara Install & Menjalankan Lokal

1. Clone repo dan buat virtual environment:
   ```bash
   git clone <repo-url>
   cd telegram_ai_bot
   python -m venv venv
   source venv/bin/activate  # atau venv\Scripts\activate untuk Windows
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Setup environment variables. Buat file `.env` di root project:
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   HF_TOKEN=your_huggingface_api_token_here
   HF_MODEL=meta-llama/Meta-Llama-3-8B-Instruct
   ADMIN_IDS=123456789,987654321
   MAX_USER_TOKENS=2000
   RATE_LIMIT_PER_MINUTE=5
   TEMPERATURE=0.7
   TOP_P=0.9
   MAX_NEW_TOKENS=1024
   ```

4. Jalankan bot:
   ```bash
   python main.py
   ```

## Struktur Project

```
telegram_ai_bot/
├── main.py              # Entry point
├── requirements.txt     # Dependencies
├── .env                 # Environment variables (jangan commit!)
├── Dockerfile           # Docker image definition
├── README.md           # Documentation
└── src/
    ├── __init__.py
    ├── config.py       # Configuration management
    ├── database.py     # SQLite database & CRUD operations
    ├── handlers.py     # Telegram message handlers
    ├── hf_client.py    # HuggingFace API integration
    ├── middlewares.py  # Rate limiting & input validation
    ├── prompts.py      # System prompts
    ├── server.py       # FastAPI health check endpoint
    └── __pycache__/
└── logs/
    └── bot.log         # Application logs
```

## Technology Stack

| Component | Tech |
|-----------|------|
| **Bot Framework** | python-telegram-bot v20+ (async) |
| **API** | HuggingFace Inference (Llama-3) |
| **Database** | SQLite + aiosqlite |
| **Web Server** | FastAPI |
| **HTTP Client** | httpx (async) |
| **Retry Logic** | tenacity |
| **Containerization** | Docker |

## Key Features Breakdown

### 1. Persistent Memory (`database.py`)
- SQLite storage untuk conversation history per user
- Context trimming: Keep only recent N messages
- User stats tracking

### 2. Streaming Response (`handlers.py` + `hf_client.py`)
- Server-Sent Events (SSE) style streaming dari HF API
- Chunks dikirim secara real-time ke user
- Simulasi ChatGPT-like response

### 3. Robustness
- **Retry Mechanism**: Exponential backoff untuk HF API failures
- **Timeout Handling**: 30 detik default, graceful error messages
- **Rate Limiting**: Per-user rate limiter (configurable per minute)
- **Input Validation**: Strip HTML tags, content moderation

### 4. Security
- **Token Masking**: Tokens disembunyikan di logs
- **Admin-Only Commands**: `/stats` hanya untuk admin
- **Input Sanitization**: Max token limit (DoS prevention)

### 5. Health Check Server
- FastAPI endpoint di port `8000` untuk Kubernetes/Docker health checks

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize bot, clear history |
| `/reset` | Clear conversation history |
| `/stats` | Show global statistics (admin only) |

Regular text messages akan diarahkan ke AI model untuk response.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | - | Telegram Bot API token |
| `HF_TOKEN` | - | HuggingFace API token |
| `HF_MODEL` | `meta-llama/Meta-Llama-3-8B-Instruct` | Model ID |
| `ADMIN_IDS` | - | Comma-separated admin user IDs |
| `MAX_USER_TOKENS` | `2000` | Max input length |
| `RATE_LIMIT_PER_MINUTE` | `5` | Messages per minute limit |
| `TEMPERATURE` | `0.7` | Model temperature (0-1) |
| `TOP_P` | `0.9` | Nucleus sampling parameter |
| `MAX_NEW_TOKENS` | `1024` | Max response length |

## Docker Deployment

Build image:
```bash
docker build -t telegram-ai-bot .
```

Run container:
```bash
docker run -e BOT_TOKEN=xxx -e HF_TOKEN=yyy telegram-ai-bot
```

## Logging

Logs disimpan di `logs/bot.log` dengan rotation:
- Max size: 5MB per file
- Backup count: 3 files
- Format: `timestamp - logger_name - level - message`
- Tokens automatically masked untuk security

## Error Handling

Bot menghandle:
- ✅ Network timeouts (30s timeout on HF API)
- ✅ Rate limiting dari Telegram/HF
- ✅ Invalid/malformed API responses
- ✅ User input validation errors
- ✅ Database connection issues (retry logic)

## Performance Notes

- Async/await untuk concurrent request handling
- Connection pooling untuk database operations
- Efficient SQLite queries dengan proper indexing
- Memory-efficient streaming (chunk-based processing)

## Dependencies

- `python-telegram-bot>=20.0` - Telegram Bot API wrapper
- `aiosqlite` - Async SQLite driver
- `httpx` - Async HTTP client
- `tenacity` - Retry library
- `fastapi` - Web framework (health checks)
- `uvicorn` - ASGI server
- `python-dotenv` - Environment variable management

## Future Improvements

- [ ] Add image generation capability  
- [ ] Implement document upload & analysis
- [ ] Add voice message support
- [ ] Implement conversation export feature
- [ ] Add user preference settings
- [ ] Performance metrics dashboard

## License

MIT License

## Support

Untuk bug reports atau features requests, buka issue di repository.
