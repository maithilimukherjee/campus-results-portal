import firebase_admin
from firebase_admin import credentials, auth
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase Admin
KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred)

def promote_to_admin(uid: str):
    try:
        # Stamp custom claim: role = admin
        auth.set_custom_user_claims(uid, {"role": "admin"})
        print(f" SUCCESS: User {uid} has been elevated to ADMIN.")
    except Exception as e:
        print(f" ERROR: {e}")

if __name__ == "__main__":
    # Paste the UID from Step 1 here
    target_uid = "o9piyLmZMTenMYaOotI6MMmAk852"
    promote_to_admin(target_uid)