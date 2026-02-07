from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import uvicorn
import os
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from cachetools import TTLCache

load_dotenv()

# --- INITIALIZATION ---
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Amzoon Music API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - CRITICAL for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=False,  # Must be False when using wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SERVICES ---
from services.youtube import YouTubeService
from services.search import search_service
from services.recommendations import recommendation_service
from services.sync import sync_service
from services.firebase_db import firebase_db
from services.device_manager import device_manager

yt_service = YouTubeService()
search_cache = TTLCache(maxsize=1000, ttl=3600)

class HistoryItem(BaseModel):
    user_id: str
    video_id: str
    title: str
    artist: str
    thumbnail: str
    completed: bool = False

# --- ROUTES ---

@app.get("/")
async def root():
    return {"message": "Welcome to Amzoon Music API"}

@app.get("/status")
async def status():
    return {"status": "ok", "version": "1.0.0"}

# --- DEVICE MANAGEMENT ---

class DeviceRegisterRequest(BaseModel):
    user_id: str
    device_id: str
    device_name: str
    platform: str
    user_agent: str = ""

class SetActiveDeviceRequest(BaseModel):
    user_id: str
    device_id: str

@app.post("/devices/register")
async def register_device(req: DeviceRegisterRequest):
    """Register a new device for a user."""
    success = device_manager.register_device(
        req.user_id,
        req.device_id,
        {
            "name": req.device_name,
            "platform": req.platform,
            "userAgent": req.user_agent
        }
    )
    if success:
        return {"status": "registered", "device_id": req.device_id}
    raise HTTPException(status_code=500, detail="Failed to register device")

@app.post("/devices/set-active")
async def set_active_device(req: SetActiveDeviceRequest):
    """Set the active playback device for a user."""
    success = device_manager.set_active_device(req.user_id, req.device_id)
    if success:
        # Broadcast device switch to all connected devices via WebSocket
        await sync_service.broadcast_device_switch(req.user_id, req.device_id)
        return {"status": "active_device_set", "device_id": req.device_id}
    raise HTTPException(status_code=404, detail="Device not found")

@app.get("/devices/list")
async def list_devices(user_id: str):
    """Get all devices for a user."""
    devices = device_manager.get_user_devices(user_id)
    active_device = device_manager.get_active_device(user_id)
    return {
        "devices": devices,
        "active_device_id": active_device
    }

@app.post("/devices/heartbeat")
async def device_heartbeat(user_id: str, device_id: str):
    """Update device heartbeat to keep it alive."""
    success = device_manager.update_device_heartbeat(user_id, device_id)
    if success:
        return {"status": "heartbeat_updated"}
    raise HTTPException(status_code=404, detail="Device not found")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/search")
@limiter.limit("50/minute")
async def search(request: Request, q: str, user_id: str = None):
    try:
        if q in search_cache:
            return {"query": q, "results": search_cache[q], "cached": True}
        print(f"DEBUG: Searching for '{q}' with user_id={user_id}")
        results = await search_service.search_songs(q, user_id=user_id)
        search_cache[q] = results
        return {"query": q, "results": results, "cached": False}
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"ERROR in /search: {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/artist/{channel_id}")
async def get_artist(channel_id: str):
    data = await yt_service.get_artist_details(channel_id)
    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])
    return data

@app.post("/user/history")
def add_history(item: HistoryItem):
    try:
        data = item.dict()
        entry_id = firebase_db.add_play_history(item.user_id, data, completed=item.completed)
        return {"status": "added", "entry_id": entry_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.patch("/user/history/{user_id}/{entry_id}")
def update_history(user_id: str, entry_id: str, data: Dict[str, Any]):
    try:
        firebase_db.update_play_history(user_id, entry_id, data)
        return {"status": "updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/user/search-history")
def add_search_history(user_id: str, query: str):
    try:
        firebase_db.add_search_history(user_id, query)
        return {"status": "added"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/user/skip")
def add_skip(item: HistoryItem):
    try:
        data = item.dict()
        firebase_db.add_skip_history(item.user_id, data)
        return {"status": "skipped"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/user/history/{user_id}")
def get_history(user_id: str):
    try:
        return firebase_db.get_play_history(user_id)
    except Exception as e:
        import traceback
        with open("backend_error.log", "a") as f:
            f.write(f"Error in get_history: {traceback.format_exc()}\n")
        print(f"Error in get_history: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/recommendations")
async def get_recommendations(user_id: str):
    try:
        return await recommendation_service.get_personalized_recommendations(user_id)
    except Exception as e:
        import traceback
        with open("backend_error.log", "a") as f:
            f.write(f"Error in recommendations: {traceback.format_exc()}\n")
        print(f"Error in recommendations: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/recommendations/daily-mix")
async def get_daily_mix(user_id: str):
    return await recommendation_service.get_daily_mix(user_id)

@app.get("/recommendations/recent-context")
async def get_recent_context(user_id: str):
    return await recommendation_service.get_recent_context(user_id)

@app.get("/autoplay/next")
async def get_autoplay_next(user_id: str, current_song_id: str):
    return await recommendation_service.get_autoplay_next(user_id, current_song_id)

# --- Collections & Metadata ---
@app.post("/songs/{song_id}/metadata")
def save_song_metadata(song_id: str, data: Dict[str, Any]):
    firebase_db.save_song_metadata(song_id, data)
    return {"status": "saved"}

@app.get("/collections/{user_id}")
def get_collections(user_id: str):
    return {"collections": firebase_db.get_user_collections(user_id)}

@app.post("/collections/{user_id}")
def create_collection(user_id: str, name: str):
    key = firebase_db.create_collection(user_id, name)
    return {"status": "created", "playlist_id": key}

@app.post("/collections/{user_id}/{playlist_id}/songs")
def add_to_collection(user_id: str, playlist_id: str, song_id: str):
    firebase_db.add_to_collection(user_id, playlist_id, song_id)
    return {"status": "added"}

@app.get("/collections/{user_id}/{playlist_id}/songs")
def get_collection_songs(user_id: str, playlist_id: str):
    song_ids = firebase_db.get_collection_songs(user_id, playlist_id)
    songs = []
    for sid in song_ids:
        # Fetch metadata for each song to display in playlist
        meta = firebase_db.get_song_metadata(sid)
        # Verify if meta is empty? If so, we only have ID.
        songs.append({"id": sid, **meta})
    return {"playlist_id": playlist_id, "songs": songs}

@app.post("/admin/train-ml")
def train_ml():
    try:
        from services.ml_recommender import ml_recommender
        ml_recommender.train_als_model()
        return {"status": "training triggered"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/stream/{video_id}")
async def get_stream(video_id: str):
    data = await yt_service.get_stream_url(video_id)
    if not data:
        raise HTTPException(status_code=404, detail="Could not extract stream URL")
    return {"video_id": video_id, **data}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    print(f"WebSocket connection attempt for user: {user_id}")
    await sync_service.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            await sync_service.broadcast_to_user(user_id, data, sender=websocket)
    except WebSocketDisconnect:
        sync_service.disconnect(websocket, user_id)
    except Exception as e:
        print(f"WS Error: {e}")
        sync_service.disconnect(websocket, user_id)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
