import yt_dlp
from typing import List, Dict, Any

class YouTubeService:
    def __init__(self):
        self.ydl_opts_search = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
        }
        self.ydl_opts_stream = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': False, # Allow it to raise so we catch the error
            'logtostderr': False,
            'no_color': True,
            'source_address': '0.0.0.0', 
        }
        self.stream_cache = {} # video_id -> {url, info, timestamp}

    async def search_songs(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Delegates robust search to specialized search_service."""
        try:
            from services.search import search_service
            # search_service.search_songs is now async
            return await search_service.search_songs(query, limit)
        except Exception as e:
            print(f"Error during search delegation: {e}")
            return []

    async def get_stream_url(self, video_id: str) -> Dict[str, Any]:
        import time
        import asyncio
        loop = asyncio.get_running_loop()

        if not video_id:
            print("ERROR: get_stream_url received empty video_id")
            return None

        # 1. Check Cache (2 hour TTL)
        now = time.time()
        if video_id in self.stream_cache:
            cache_entry = self.stream_cache[video_id]
            if now - cache_entry['timestamp'] < 7200: # 2 hours
                print(f"DEBUG: Serving Cached Stream for {video_id}")
                return cache_entry['data']

        # 2. Extract fresh URL
        print(f"DEBUG: Extracting stream for: {video_id}")
        
        def _blocking_extract():
            with yt_dlp.YoutubeDL(self.ydl_opts_stream) as ydl:
                url = f"https://www.youtube.com/watch?v={video_id}"
                info = ydl.extract_info(url, download=False)
                return info

        try:
            info = await loop.run_in_executor(None, _blocking_extract)
            
            # Some videos might return a stream_url in a different field
            stream_url = info.get('url')
            if not stream_url and 'formats' in info:
                # Fallback: get the first audio-only format
                audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_formats:
                    stream_url = audio_formats[0].get('url')

            if not stream_url:
                print(f"ERROR: No stream URL found for {video_id}")
                return None

            result = {
                "stream_url": stream_url,
                "title": info.get('title'),
                "artist": info.get('uploader'),
                "album": info.get('album') or info.get('title'), # Fallback to title
                "thumbnail": info.get('thumbnail')
            }
            # Update Cache
            self.stream_cache[video_id] = {
                "data": result,
                "timestamp": now
            }
            return result
        except Exception as e:
            print(f"Error extracting stream URL for {video_id}: {e}")
            return None
        
    def clear_cache(self):
        self.stream_cache = {}

    async def get_artist_details(self, channel_id: str) -> Dict[str, Any]:
        """Fetch artist details and top songs from their channel."""
        import asyncio
        loop = asyncio.get_running_loop()

        def _blocking_artist_fetch():
            with yt_dlp.YoutubeDL(self.ydl_opts_search) as ydl:
                url = f"https://www.youtube.com/channel/{channel_id}"
                return ydl.extract_info(url, download=False)

        try:
            info = await loop.run_in_executor(None, _blocking_artist_fetch)
            
            entries = info.get('entries', [])
            songs = []
            
            for entry in entries[:20]:
                if not entry: 
                    continue
                
                duration = entry.get('duration', 0)
                if duration and duration < 60: 
                    continue
                    
                songs.append({
                    "id": entry.get('id'),
                    "title": entry.get('title'),
                    "artist": info.get('uploader') or info.get('title'),
                    "thumbnail": entry.get('thumbnails', [{}])[0].get('url'),
                    "duration": duration
                })
                
            return {
                "id": channel_id,
                "name": info.get('uploader') or info.get('title'),
                "description": info.get('description', ''),
                "thumbnails": info.get('thumbnails', []),
                "songs": songs
            }
        except Exception as e:
            print(f"Error fetching artist details: {e}")
            return {"error": str(e)}

yt_service = YouTubeService()
