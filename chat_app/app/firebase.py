import os
import typing
import firebase_admin
from firebase_admin import auth, credentials, db
from log import log


class FirebaseDB():
    def __init__(self):
        log("FirebaseDB.__init__() called")
        # Dir to key
        current_dir = os.path.dirname(os.path.abspath(__file__))
        firebase_key_dir = os.path.join(current_dir, "firebase_key")
        self.cred_path = os.path.join(firebase_key_dir, "zalophake.json")
        self.db_url = "https://zalophake-bf746-default-rtdb.firebaseio.com/"
        self.root_path = "/"
        self.app = None
        self.ref = None
        return

    def connect(self) -> None:
        # Initialize Firebase Admin SDK and set database reference
        # Authenticate
        self.cred = credentials.Certificate(self.cred_path)
        self.app = firebase_admin.initialize_app(self.cred, {"databaseURL": self.db_url})

        # Get references to DB parent nodes
        self.ref = db.reference(self.root_path)
        self.users_ref = db.reference("Users")
        log(self.app.name)
        log("Connected to Firebase Realtime Database")
        return

    def disconnect(self) -> None:
        # Firebase Realtime Database does not require explicit disconnection
        self.app = None
        self.ref = None
        log("Disconnected from Firebase Realtime Database")
        return

    def insert(self, path: str, data: typing.Any) -> bool:
        # Insert data into Firebase path
        log(f"[Debug] Firebase insert \"{data}\" to \"{path}\"")
        try:
            new_ref = db.reference(path)
        except ValueError:
            log(f"[Error] Cannot get reference from {path}")
            return False
        new_ref.set(data)
        return True  # Firebase generates a unique key

    def query(self, path: str, response: typing.Optional[typing.Any]) -> bool:
        # Find data matching a path
        log(f"[Debug] Firebase query \"{path}\"")
        try:
            response["body"] = db.reference(path).get()
        except ValueError:
            log(f"[Error] Cannot query {path}")
            return False
        return True

    def update(self, path: str, data: typing.Any, response: typing.Optional[typing.Any]) -> bool:
        # Update data matching a path
        log(f"[Debug] Firebase update \"{data}\" to \"{path}\"")
        if not self.query(path, response=response):
            return False
        self.insert(path, data)
        return True

    def delete(self, path: str, child_key: str, response: typing.Optional[typing.Any]) -> bool:
        # Delete data matching a path
        log(f"[Debug] Firebase delete data at \"{path}\", child key \"{child_key}\"")
        if not self.query(path, response=response):
            return False
        new_ref = db.reference(path)
        new_ref.child(child_key).delete()
        return True
    
    def create_user(self, *args, **kwargs):
        try:
            user = auth.create_user(*args, **kwargs)
            return user
        except Exception as e:
            log(f"Error creating user: {e}")
            return None

    def query_user_by_email(self, email):
        try:
            user = auth.get_user_by_email(email)
            return user
        except Exception as e:
            log(f"Error querying user: {e}")
            return None
    
    def query_user_by_phone_number(self, phone):
        try:
            user = auth.get_user_by_phone_number(phone)
            return user
        except Exception as e:
            log(f"Error querying user: {e}")
            return None
    
    def query_user_id(self, uid):
        try:
            user = auth.get_user(uid)
            return user
        except Exception as e:
            log(f"Error querying user: {e}")
            return None
    
    def update_user(self, *args, **kwargs):
        try:
            user = auth.update_user(*args, **kwargs)
            return user
        except Exception as e:
            log(f"Error updating user: {e}")
            return None

    def verify_token(self, id_token):
        # Verify firebase token from FE
        try:
            decoded_token = auth.verify_id_token(id_token)
            return decoded_token
        except Exception as e:
            log(f"Invalid token: {e}")
            return None

