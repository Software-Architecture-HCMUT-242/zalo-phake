import json
import os
import typing

import firebase_admin
from firebase_admin import credentials, db, firestore


class FirebaseDB:
    def __init__(self):
        print("FirebaseDB.__init__() called")
        # Dir to key
        # should fix this to use GOOGLE_APPLICATION_CREDENTIALS env https://firebase.google.com/docs/admin/setup#initialize_the_sdk_in_non-google_environments
        current_dir = os.path.dirname(os.path.abspath(__file__))
        firebase_key_dir = os.path.join(current_dir, "firebase_key")
        self.cred_path = os.path.join(firebase_key_dir, "zalophake.json")
        self.db_url = "https://zalophake-bf746-default-rtdb.firebaseio.com/"
        self.root_path = "/"
        self.app = None
        self.ref = None
        self.connect()
        return

    def get_realtime_db(self) -> db.Reference:
        # Return a reference to the root path
        return self.ref
    
    def get_firestore_db(self) -> firebase_admin.db:
        # Return a reference to the Firebase client
        return firestore.client()
    
    def connect(self) -> None:
        # Initialize Firebase Admin SDK and set database reference
        # Authenticate using credentials from environment variable
        cert_json = os.getenv("FIREBASE_SECRET")
        if not cert_json:
            raise ValueError("Environment variable FIREBASE_SECRET is not set")
        cert_dict = json.loads(cert_json)
        if type(cert_dict) == str:
            cert_dict = json.loads(cert_dict)
        cred = credentials.Certificate(cert_dict)
        self.app = firebase_admin.initialize_app(credential=cred,
            options={"databaseURL": self.db_url}
        )

        # Get references to DB parent nodes
        self.ref = db.reference(self.root_path)
        self.users_ref = db.reference("Users")
        print(self.app.name)
        print("Connected to Firebase Realtime Database")
        return

    def disconnect(self) -> None:
        # Firebase Realtime Database does not require explicit disconnection
        self.app = None
        self.ref = None
        print("Disconnected from Firebase Realtime Database")
        return

    def insert(self, path: str, data: typing.Any) -> bool:
        # Insert data into Firebase path
        print(f'[Debug] Firebase insert "{data}" to "{path}"')
        try:
            new_ref = db.reference(path)
        except ValueError:
            print(f"[Error] Cannot get reference from {path}")
            return False
        new_ref.set(data)
        return True  # Firebase generates a unique key

    def query(self, path: str, response: typing.Optional[typing.Any]) -> bool:
        # Find data matching a path
        print(f'[Debug] Firebase query "{path}"')
        try:
            response["body"] = db.reference(path).get()
        except ValueError:
            print(f"[Error] Cannot query {path}")
            return False
        return True

    def update(
        self, path: str, data: typing.Any, response: typing.Optional[typing.Any]
    ) -> bool:
        # Update data matching a path
        print(f'[Debug] Firebase update "{data}" to "{path}"')
        if not self.query(path, response):
            return False
        self.insert(path, data)
        return True

    def delete(self, path: str, response: typing.Optional[typing.Any]) -> bool:
        # Delete data matching a path
        print(f'[Debug] Firebase delete data at "{path}"')
        if not self.query(path, response):
            return False
        new_ref = db.reference(path)
        new_ref.child(response).delete()
        return True
