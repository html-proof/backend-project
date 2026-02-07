from fastapi import WebSocket, WebSocketDisconnect
from services.device_manager import device_manager
from services.firebase_db import firebase_db

class SyncService:
    def __init__(self):
        # Map user_id -> list of websockets
        self.rooms: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        print(f"DEBUG: SyncService.connect starting for {user_id}")
        await websocket.accept()
        print(f"DEBUG: SyncService.connect accepted for {user_id}")
        if user_id not in self.rooms:
            self.rooms[user_id] = []
        self.rooms[user_id].append(websocket)
        print(f"User {user_id} connected. Total connections: {len(self.rooms[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.rooms:
            if websocket in self.rooms[user_id]:
                self.rooms[user_id].remove(websocket)
            if not self.rooms[user_id]:
                del self.rooms[user_id]
        print(f"User {user_id} disconnected.")

    async def broadcast_to_user(self, user_id: str, message: dict, sender: WebSocket = None):
        """Broadcasts a message to all active sessions of a specific user."""
        if user_id in self.rooms:
            for connection in self.rooms[user_id]:
                # Don't send back to the sender
                if sender and connection == sender:
                    continue
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error broadcasting to {user_id}: {e}")

    async def handle_playback_update(self, user_id: str, device_id: str, state: dict, sender: WebSocket = None):
        """
        Handle playback state update with device validation.
        Only active device can update playback.
        """
        # Validate device control
        if not device_manager.validate_device_control(user_id, device_id):
            # Send rejection message to sender
            active_device = device_manager.get_active_device(user_id)
            if sender:
                try:
                    await sender.send_json({
                        "type": "playback_controlled_elsewhere",
                        "active_device_id": active_device,
                        "message": "Playback is controlled on another device"
                    })
                except Exception as e:
                    print(f"Error sending rejection: {e}")
            return False

        # Update playback state in Firebase
        firebase_db.set_playback_state(user_id, state)

        # Broadcast to other devices
        await self.broadcast_to_user(user_id, {
            "type": "playback_state_update",
            "state": state
        }, sender=sender)

        return True

    async def broadcast_device_switch(self, user_id: str, new_active_device_id: str):
        """
        Broadcast device switch event to all user's devices.
        """
        await self.broadcast_to_user(user_id, {
            "type": "device_switched",
            "active_device_id": new_active_device_id,
            "message": f"Playback control switched to device {new_active_device_id}"
        })

sync_service = SyncService()
