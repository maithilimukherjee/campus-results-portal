import requests
import json
import os
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# 1. Fetch the API Key the Python way
API_KEY = os.getenv("apiKey")

def login_and_get_token(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if "idToken" in data:
        print("\nSUCCESS! Here is your JWT Token (Copy everything below):\n")
        print(data["idToken"])
        print("\n")
    else:
        print("❌ Login Failed:", data.get("error", {}).get("message", "Unknown Error"))

if __name__ == "__main__":
    # 2. Put the test email and password you created in Firebase Auth here
    login_and_get_token("cs24.maithili.mukherjee@stcet.ac.in", "123456789123456789")