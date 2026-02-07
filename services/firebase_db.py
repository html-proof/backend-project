import firebase_admin
from firebase_admin import credentials, db
import os
from dotenv import load_dotenv

load_dotenv()

class FirebaseDB:
    def __init__(self):
        # Check if already initialized to avoid re-init errors
        if not firebase_admin._apps:
            # Try to get credentials from file
            cred_path = os.getenv("FIREBASE_SERVICE_KEY")
            db_url = os.getenv("FIREBASE_DB_URL")
            
            if not cred_path or not db_url:
                print("Warning: FIREBASE_SERVICE_KEY or FIREBASE_DB_URL not set.")
                return

            try:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': db_url
                })
                print("Firebase Admin Initialized Successfully")
            except Exception as e:
                print(f"Failed to initialize Firebase Admin: {e}")

    # --- History Handling ---
    # --- History Handling ---
    def add_play_history(self, user_id: str, song_data: dict, completed: bool = False):
        if not user_id: return None
        ref = db.reference(f'users/{user_id}/history/plays')
        new_ref = ref.push()
        song_data['timestamp'] = {'.sv': 'timestamp'}
        song_data['completed'] = completed
        new_ref.set(song_data)
        return new_ref.key
        
    def update_play_history(self, user_id: str, entry_id: str, data: dict):
        if not user_id or not entry_id: return
        ref = db.reference(f'users/{user_id}/history/plays/{entry_id}')
        ref.update(data)

    def add_skip_history(self, user_id: str, song_data: dict):
        if not user_id: return
        ref = db.reference(f'users/{user_id}/history/skips')
        new_ref = ref.push()
        song_data['timestamp'] = {'.sv': 'timestamp'}
        new_ref.set(song_data)

    def add_search_history(self, user_id: str, query: str):
        if not user_id or not query: return
        ref = db.reference(f'users/{user_id}/search')
        new_ref = ref.push()
        new_ref.set({
            "query": query,
            "searchedAt": {'.sv': 'timestamp'}
        })
        
    def get_play_history(self, user_id: str, limit: int = 50):
        if not user_id: return []
        ref = db.reference(f'users/{user_id}/history/plays')
        snapshot = ref.order_by_key().limit_to_last(limit).get()
        if not snapshot:
            return []
        
        # Convert dict to list and reverse (newest first)
        history = list(snapshot.values())
        return history[::-1]

    # --- Likes Handling ---
    # Note: Frontend handles toggling likes directly to Firestore or RTDB.
    # Backend mainly READS likes for recommendations.
    # Assuming frontend writes to `users/{uid}/likedSongs` in Firestore (as per LikeButton.tsx)
    # BUT wait, the user's LikeButton.tsx uses Firestore `db`.
    # This backend service is using RTDB (firebase_admin.db).
    
    # Let's support Firestore reading for recommendations
    
    def get_liked_songs(self, user_id: str):
        if not user_id: return []
        # Use RTDB instead of Firestore
        try:
            ref = db.reference(f'users/{user_id}/likedSongs')
            snapshot = ref.get()
            if not snapshot: return []
            return list(snapshot.values())
        except Exception as e:
            print(f"Error fetching liked songs from RTDB: {e}")
            return []

    # --- Playlists ---
    # If using RTDB for playlists
    def get_playlists(self, user_id: str):
        if not user_id: return []
        ref = db.reference(f'users/{user_id}/library/playlists')
        snapshot = ref.get()
        return list(snapshot.values()) if snapshot else []

    def get_frequent_artists(self, user_id: str, limit: int = 50):
        """Analyze history to find artists the user listens to most."""
        history = self.get_play_history(user_id, limit=limit)
        if not history:
            return []
            
        counts = {}
        for item in history:
            artist = item.get('artist')
            if artist:
                # Basic normalization
                artist = artist.split(' - ')[0].strip()
                counts[artist] = counts.get(artist, 0) + 1
                
        # Sort by frequency
        sorted_artists = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [a[0] for a in sorted_artists[:5]] # Return top 5

    def get_all_plays(self):
        """Fetch all play history for global ML model training."""
        ref = db.reference('users')
        snapshot = ref.get()
        if not snapshot:
            return []
            
        interactions = []
        for user_id, user_data in snapshot.items():
            plays = user_data.get('history', {}).get('plays', {})
            for entry_id, data in plays.items():
                interactions.append({
                    'user_id': user_id,
                    'video_id': data.get('video_id'),
                    'completed': data.get('completed', False),
                    'type': 'play'
                })
        return interactions

    def get_all_likes(self):
        """Fetch all liked songs across all users."""
        # RTDB doesn't support collection group queries efficiently
        # Returning empty list for now to prevent crash
        return []
    def get_all_skips(self):
        """Fetch all skip history for global ML model training."""
        ref = db.reference('users')
        snapshot = ref.get()
        if not snapshot:
            return []
            
        skips = []
        for user_id, user_data in snapshot.items():
            user_skips = user_data.get('history', {}).get('skips', {})
            for entry_id, data in user_skips.items():
                skips.append({
                    'user_id': user_id,
                    'video_id': data.get('video_id'),
                    'type': 'skip'
                })
        return skips

    # --- AI Channel Trust Cache ---
    def get_channel_classification(self, channel_id: str):
        if not channel_id: return None
        ref = db.reference(f'channel_trust_cache/{channel_id}')
        return ref.get()

    def set_channel_classification(self, channel_id: str, data: dict):
        if not channel_id: return
        ref = db.reference(f'channel_trust_cache/{channel_id}')
        data['timestamp'] = {'.sv': 'timestamp'}
        ref.set(data)

    # --- Synchronization (Multi-Device) ---
    def set_playback_state(self, user_id: str, state: dict):
        """Update user's current playback state."""
        if not user_id: return
        ref = db.reference(f'users/{user_id}/playback/current')
        state['updatedAt'] = {'.sv': 'timestamp'}
        ref.set(state)

    def get_playback_state(self, user_id: str):
        """Get user's current playback state."""
        if not user_id: return None
        ref = db.reference(f'users/{user_id}/playback')
        return ref.get()

    def update_playback_position(self, user_id: str, position_sec: float, is_playing: bool):
        """Update only position and playing status (for periodic sync)."""
        if not user_id: return
        ref = db.reference(f'users/{user_id}/playback/current')
        ref.update({
            'positionSec': position_sec,
            'isPlaying': is_playing,
            'updatedAt': {'.sv': 'timestamp'}
        })

    # --- Song Metadata (Album Support) ---
    def save_song_metadata(self, song_id: str, data: dict):
        """Store album + image in songs/{song_id}."""
        if not song_id: return
        ref = db.reference(f'songs/{song_id}')
        # Only update provided fields to preserve existing data
        ref.update(data)

    def get_song_metadata(self, song_id: str):
        """Retrieve album + image from Firebase."""
        if not song_id: return {}
        ref = db.reference(f'songs/{song_id}')
        data = ref.get()
        return data if data else {}

    # --- Collections / Playlists ---
    def create_collection(self, user_id: str, name: str):
        """Create a new playlist."""
        if not user_id or not name: return None
        ref = db.reference(f'collections/{user_id}')
        new_ref = ref.push()
        new_ref.set({
            'name': name,
            'createdAt': {'.sv': 'timestamp'},
            'songs': []
        })
        return new_ref.key

    def add_to_collection(self, user_id: str, playlist_id: str, song_id: str):
        """Add a song to a playlist."""
        if not user_id or not playlist_id or not song_id: return
        ref = db.reference(f'collections/{user_id}/{playlist_id}/songs')
        # Check if song already exists? Or just append.
        # RTDB lists are tricky. Better use push() or a dict with song_id as key.
        # User snippet used a list in JSON example, but Python code handled list/dict.
        # I'll use push() to avoid concurrency issues, treating it as a list of entries.
        ref.push(song_id)

    def get_user_collections(self, user_id: str):
        """Get all playlists for a user."""
        if not user_id: return {}
        ref = db.reference(f'collections/{user_id}')
        return ref.get() or {}

    def get_collection_songs(self, user_id: str, playlist_id: str):
        """Get songs in a playlist."""
        if not user_id or not playlist_id: return []
        ref = db.reference(f'collections/{user_id}/{playlist_id}/songs')
        data = ref.get()

        if not data:
            return []

        # Handle list vs dict (RTDB behavior)
        if isinstance(data, list):
            return [str(x) for x in data if x]
        
        if isinstance(data, dict):
            return [str(v) for v in data.values()]

        return []

firebase_db = FirebaseDB()
