from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram AI Bot Health Check")

@app.get("/")
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Telegram AI Bot"}