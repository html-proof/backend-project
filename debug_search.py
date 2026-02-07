import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

try:
    print("Initializing SearchService...")
    from services.search import SearchService
    search_service = SearchService()
    
    print("Running search for 'test'...")
    results = search_service.search_songs("test", user_id="test_user")
    
    print("\nTesting get_play_history...")
    from services.firebase_db import firebase_db
    history = firebase_db.get_play_history("test_user_id")
    print(f"History retrieved: {len(history)} items")
    
except Exception as e:
    import traceback
    print("\nCRASH DETECTED!")
    traceback.print_exc()
