import json
import os

import firebase_admin
import google.cloud.firestore
from firebase_admin import credentials, db, firestore
import logging


logger = logging.getLogger(__name__)

class FirebaseDB:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseDB, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
        logger.info("FirebaseDB.__init__() called")
        # Dir to key
        # should fix this to use GOOGLE_APPLICATION_CREDENTIALS env https://firebase.google.com/docs/admin/setup#initialize_the_sdk_in_non-google_environments
        current_dir = os.path.dirname(os.path.abspath(__file__))
        firebase_key_dir = os.path.join(current_dir, "firebase_key")
        self.cred_path = os.path.join(firebase_key_dir, "zalophake.json")
        self.db_url = "https://zalophake-bf746-default-rtdb.firebaseio.com/"
        self.root_path = "/"
        self.app = None
        self.db = None
        self.firestore_db = None
        self.connect()
        self.initialized = True
        return

    def get_realtime_db(self) -> db:
        # Return a reference to the root path
        return self.db
    
    def get_firestore_db(self) -> google.cloud.firestore.Client:
        # Return a reference to the Firebase client
        return self.firestore_db

    def connect(self) -> None:
        # Initialize Firebase Admin SDK and set database reference
        # to Authenticate using credentials from environment variable
        cert_json = os.getenv("FIREBASE_SECRET")
        if not cert_json:
            raise ValueError("Environment variable FIREBASE_SECRET is not set")
        cert_dict = json.loads(cert_json)
        if type(cert_dict) == str:
            cert_dict = json.loads(cert_dict)
        cred = credentials.Certificate(cert_dict)

        self.app = firebase_admin.initialize_app(
            credential=cred,
            options={"databaseURL": self.db_url},
        )
        self.firestore_db = firestore.client(self.app)
        self.db = db

        logger.info(f"Connected to Firebase Realtime Database. App name: {self.app.name}")
        return
