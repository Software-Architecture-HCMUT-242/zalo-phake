from ..firebase import realtime_db

DB_USER_PATH = "/User/"

def get_user_info(user_id: str) -> dict:
    """
    Get user data from Firebase Realtime Database by user ID.
    """
    user_ref = realtime_db.reference(DB_USER_PATH + user_id)
    user_data = user_ref.get()
    return user_data