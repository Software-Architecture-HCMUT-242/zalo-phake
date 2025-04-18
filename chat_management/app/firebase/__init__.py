import firebase_admin
import google.cloud.firestore
from firebase_admin import db

from .firebase import FirebaseDB

firebase_db = FirebaseDB()
realtime_db: firebase_admin.db = firebase_db.get_realtime_db()
firestore_db: google.cloud.firestore.Client = firebase_db.get_firestore_db()
