import sys
import os
import firebase_admin
from firebase_admin import credentials


class DB:
    def __init__(self):
        print("DB.__init__() called")
        current_dir = os.path.dirname(os.path.abspath(__file__))
        firebase_key_dir = os.path.join(current_dir, "firebase_key")
        key_path = os.path.join(firebase_key_dir, "zalophake.json")
        self.cred = credentials.Certificate(key_path)
        self.app = firebase_admin.initialize_app(self.cred)
        print(self.app.name)
        return
    
    def get_all_documents():
        users_ref = db.collection("users")
        docs = users_ref.stream()
        for doc in docs:
            print(f"{doc.id} => {doc.to_dict()}")

    def create(self, key, value):
        ref = db.reference(key)
        return 
        
