import os
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase Admin SDK once
KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred)