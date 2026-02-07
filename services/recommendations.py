from typing import List, Dict, Any
import random
from services.firebase_db import firebase_db
from services.search import search_service
# We'll use a direct yt_service import if needed for raw stuff, 
# but recommendation uses search_service for quality hits
from services.youtube import YouTubeService
from services.ml_recommender import ml_recommender
import os
import asyncio

yt_service = YouTubeService()

class RecommendationService:
    async def get_personalized_recommendations(self, user_id: str):
        recommendations = []
        seen_ids = set()
        
        # 1. Try ML (ALS) Recommendations First
        try:
            ml_results = ml_recommender.get_als_recommendations(user_id)
            for vid in ml_results:
                # Enrich minimal ML data with search
                res = await search_service.search_songs(vid, limit=1)
                if res and res[0]['id'] not in seen_ids:
                    recommendations.append(res[0])
                    seen_ids.add(res[0]['id'])
        except Exception as e:
            print(f"ML Rec failed, falling back: {e}")

        # 2. Strategy A: Based on Favorite Artists (Classical Fallback)
        try:
            top_artists = firebase_db.get_frequent_artists(user_id, limit=50)
            user_likes = firebase_db.get_liked_songs(user_id)
            for s in user_likes:
                seen_ids.add(s.get('id') or s.get('video_id'))
        except Exception as e:
            print(f"Error fetching user profile: {e}")
            top_artists = []

        if top_artists and len(recommendations) < 20:
            for i, artist in enumerate(top_artists):
                fetch_limit = 10 if i == 0 else 5
                results = await search_service.search_songs(f"best of {artist}", limit=fetch_limit)
                for song in results:
                    if song['id'] not in seen_ids:
                        recommendations.append(song)
                        seen_ids.add(song['id'])
                if len(recommendations) >= 30: break

        # 3. Strategy B: Fill with trending/new if needed
        if len(recommendations) < 20:
            needed = 20 - len(recommendations)
            fillers = await search_service.search_songs("latest music hits 2024", limit=needed + 10)
            for song in fillers:
                if song['id'] not in seen_ids:
                    recommendations.append(song)
        
        # 2. Try Spotify Recommender (Offline / Content-Based)
        # Assuming spotify_recommender is imported and initialized elsewhere
        # For this exercise, we'll mock its existence and 'enabled' attribute
        class MockSpotifyRecommender:
            def __init__(self):
                self.enabled = False # Set to True to activate this path
            def recommend_for_user(self, history_ids, top_n):
                if self.enabled:
                    # Mock some Spotify-like recommendations
                    return [
                        {'id': 'spotify_track_1', 'name': 'Mock Song 1', 'artists': 'Mock Artist A'},
                        {'id': 'spotify_track_2', 'name': 'Mock Song 2', 'artists': 'Mock Artist B'}
                    ]
                return []
        
        spotify_recommender = MockSpotifyRecommender() # Initialize mock

        if spotify_recommender.enabled:
            # Get user history IDs (assuming we might have resolved some?)
            history = firebase_db.get_play_history(user_id, limit=10)
            # We need to map YouTube IDs to Spotify IDs if possible, but we likely can't.
            # So we pass whatever IDs we have. If they match the CSV, great.
            # If not, we fall back to trending from CSV.
            history_ids = [h.get('video_id', '') for h in history]
            
            spotify_recs = spotify_recommender.recommend_for_user(history_ids, top_n=15)
            if spotify_recs:
                # Transform to match our schema
                for rec in spotify_recs:
                    recommendations.append({
                        "id": rec['id'], # Spotify ID
                        "title": rec['name'],
                        "artist": rec['artists'],
                        "album": f"{rec['name']} (Single)", # Placeholder
                        "thumbnail": None, # CSV has no image
                        "duration": "3:00", # Placeholder
                        "is_spotify": True, # Flag for resolution
                        "needs_resolution": True
                    })
                print(f"Generated {len(recommendations)} Spotify recommendations")
                return recommendations

        # 3. Fallback to Online Search (Existing Logic)
        print("Fallback to Online Search Recommendations")
        # Get user context
        top_artists = firebase_db.get_frequent_artists(user_id, limit=5)
        
        # Strategy A: Collaborative Filtering (Mock/ML)
        # ...

        # Strategy B: Content Based (Search)
        query = "top hits 2024"
        if top_artists:
            artist = random.choice(top_artists)
            query = f"{artist} similar songs"
        
        return await search_service.search_songs(query, limit=20)

    async def get_daily_mix(self, user_id: str):
        try:
            top_artists = firebase_db.get_frequent_artists(user_id, limit=30)
            if not top_artists:
                return await search_service.search_songs("lofi chill beats for study", limit=12)
            
            primary_artist = top_artists[0]
            results = await search_service.search_songs(f"{primary_artist} essential mix", limit=12)
            return results
        except:
            return []

    async def get_recent_context(self, user_id: str):
        try:
            history = firebase_db.get_play_history(user_id, limit=1)
            if not history:
                return {"last_song": None, "recommendations": []}
                
            last_song = history[0]
            video_id = last_song.get('video_id')
            
            # 1. Try Content-Based ML Similarity First
            ml_results = ml_recommender.get_content_similarity(video_id)
            recommendations = []
            seen_ids = {video_id}

            if ml_results:
                for vid in ml_results:
                    res = await search_service.search_songs(vid, limit=1)
                    if res and res[0]['id'] not in seen_ids:
                        recommendations.append(res[0])
                        seen_ids.add(res[0]['id'])

            # 2. Fallback to Keyword Search
            if len(recommendations) < 8:
                search_query = f"songs similar to {last_song.get('title')} {last_song.get('artist')}"
                results = await search_service.search_songs(search_query, limit=12)
                for s in results:
                    if s['id'] not in seen_ids:
                        recommendations.append(s)
                        seen_ids.add(s['id'])
            
            return {
                "last_song": last_song,
                "recommendations": recommendations[:12]
            }
        except Exception as e:
            print(f"Error in context rec: {e}")
            return {"last_song": None, "recommendations": []}

    async def get_autoplay_next(self, user_id: str, current_song_id: str) -> List[Dict[str, Any]]:
        """Find the best next songs based on history and similarity."""
        try:
            # 1. Get user context
            top_artists = firebase_db.get_frequent_artists(user_id, limit=30)
            history = firebase_db.get_play_history(user_id, limit=20)
            
            seen_ids = {current_song_id}
            for h in history:
                vid = h.get('video_id') or h.get('id')
                if vid: seen_ids.add(vid)

            # 2. Try similarity search for current song
            current_info = await yt_service.get_stream_url(current_song_id)
            if current_info:
                query = f"songs similar to {current_info.get('title')} {current_info.get('artist')}"
                sim_results = await search_service.search_songs(query, limit=5)
                candidates = [s for s in sim_results if s['id'] not in seen_ids]
                if candidates:
                    return candidates[:3]

            # 3. Fallback to favorite artists
            if top_artists:
                artist = random.choice(top_artists[:3])
                artist_results = await search_service.search_songs(f"{artist} top songs audio", limit=5)
                candidates = [s for s in artist_results if s['id'] not in seen_ids]
                if candidates:
                    return candidates[:3]

            # 4. Ultimate fallback
            return await search_service.search_songs("top hits global 2024", limit=3)
        except Exception as e:
            print(f"Autoplay Error: {e}")
            return []

recommendation_service = RecommendationService()
