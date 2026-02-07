import pandas as pd
import numpy as np
from scipy.sparse import csr_matrix
import implicit
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from services.firebase_db import firebase_db
from services.search import search_service
import os
import pickle

class MetadataRetriever:
    """Handles mapping between item IDs and metadata (title/artist)."""
    def __init__(self):
        self._metadata_df = pd.DataFrame()

    def load_metadata(self, interactions):
        if not interactions: return
        df = pd.DataFrame(interactions)
        # Keep newest info for each video_id
        self._metadata_df = df.drop_duplicates('video_id').set_index('video_id')

    def get_info(self, video_id):
        if video_id in self._metadata_df.index:
            row = self._metadata_df.loc[video_id]
            return {"title": row.get('title'), "artist": row.get('artist')}
        return None

class InteractionProcessor:
    """Prepares the user-item interaction matrix with advanced weighting."""
    def prepare_matrix(self):
        # Implementation Pending: Need efficient way to fetch all interactions
        # For now, return empty dataframes to prevent crash
        plays = [] 
        likes = []
        skips = []

        df_plays = pd.DataFrame(plays)
        df_likes = pd.DataFrame(likes)
        df_skips = pd.DataFrame(skips)

        combined = []
        
        # 1. Process Plays (Complete: +3, Partial: +1)
        if not df_plays.empty:
            df_plays['weight'] = df_plays['completed'].apply(lambda x: 3 if x else 1)
            combined.append(df_plays[['user_id', 'video_id', 'weight']])

        # 2. Process Likes (+5)
        if not df_likes.empty:
            df_likes['weight'] = 5
            combined.append(df_likes[['user_id', 'video_id', 'weight']])

        # 3. Process Skips (-3)
        if not df_skips.empty:
            df_skips['weight'] = -3
            combined.append(df_skips[['user_id', 'video_id', 'weight']])

        if not combined: return None, None, None, None

        full_df = pd.concat(combined)
        
        # Aggregated weights per user-item pair
        agg_df = full_df.groupby(['user_id', 'video_id']).sum().reset_index()
        
        # Mapping for ALS
        agg_df['user_cat'] = agg_df['user_id'].astype('category')
        agg_df['item_cat'] = agg_df['video_id'].astype('category')
        
        user_map = dict(enumerate(agg_df['user_cat'].cat.categories))
        item_map = {id: i for i, id in enumerate(agg_df['item_cat'].cat.categories)}
        reverse_item_map = {i: id for id, i in item_map.items()}
        
        user_ids = agg_df['user_cat'].cat.codes
        item_ids = agg_df['item_cat'].cat.codes
        
        matrix = csr_matrix((agg_df['weight'], (item_ids, user_ids)))
        return matrix, user_map, item_map, reverse_item_map

class MLRecommender:
    def __init__(self):
        self.model = None
        self.user_map = {}
        self.item_map = {}
        self.reverse_item_map = {}
        self.retriever = MetadataRetriever()
        self.tfidf = TfidfVectorizer(stop_words='english')
        self.model_path = "models/als_model.pkl"
        
        if not os.path.exists("models"):
            os.makedirs("models")

    def train_als_model(self):
        processor = InteractionProcessor()
        matrix, u_map, i_map, r_map = processor.prepare_matrix()
        
        if matrix is None:
            print("Insufficient data for ML training.")
            return

        self.user_map = u_map
        self.item_map = i_map
        self.reverse_item_map = r_map
        
        # Train model
        self.model = implicit.als.AlternatingLeastSquares(factors=50, iterations=20, regularization=0.1)
        self.model.fit(matrix)
        
        # Also load metadata for content-based fallback
        self.retriever.load_metadata(firebase_db.get_all_interactions())

        with open(self.model_path, 'wb') as f:
            pickle.dump((self.model, self.user_map, self.item_map, self.reverse_item_map, self.retriever), f)
        print("Robust ML Recommender trained.")

    def get_als_recommendations(self, user_id, n=10):
        try:
            if self.model is None and os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.model, self.user_map, self.item_map, self.reverse_item_map, self.retriever = data

            if self.model is None: return []

            reverse_user_map = {v: k for k, v in self.user_map.items()}
            if user_id not in reverse_user_map: return []
            
            user_idx = reverse_user_map[user_id]
            
            # Use current model interface
            # In implicit 0.6+, recommend takes userid and a user_items matrix (optional or used internally)
            # We'll pass a dummy or the actual matrix if we had it cached. 
            # In basic usage, it just needs the ID for trained users.
            ids, scores = self.model.recommend(user_idx, csr_matrix((1, len(self.item_map))), N=n)
            
            return [self.reverse_item_map.get(idx) for idx in ids if idx in self.reverse_item_map]
        except Exception as e:
            print(f"Rec Error: {e}")
            return []

    def get_content_similarity(self, song_id, n=5):
        # ... logic remains similar but uses self.retriever._metadata_df
        try:
            df = self.retriever._metadata_df.reset_index()
            if df.empty or song_id not in df['video_id'].values: return []
            
            df['combined'] = df['title'] + " " + df['artist']
            matrix = self.tfidf.fit_transform(df['combined'])
            idx = df[df['video_id'] == song_id].index[0]
            
            sim = cosine_similarity(matrix[idx], matrix).flatten()
            indices = sim.argsort()[-(n+1):-1][::-1]
            return df.iloc[indices]['video_id'].tolist()
        except: return []

ml_recommender = MLRecommender()
