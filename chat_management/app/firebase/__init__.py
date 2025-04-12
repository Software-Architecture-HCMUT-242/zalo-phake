from firebase_admin import db

from .firebase import FirebaseDB

firebase_db = FirebaseDB()
realtime_db = firebase_db.get_realtime_db()
firestore_db: db = firebase_db.get_firestore_db()
