import firebase_admin
from firebase_admin import credentials

class DB:
    def __init__(self):
        print("DB.__init__() called")
        self.cred = credentials.Certificate("firebase_key/zalophake-bf746-firebase-adminsdk-fbsvc-61c19da529.json")
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
        
