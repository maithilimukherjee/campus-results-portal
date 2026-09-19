import uuid
import random
from locust import HttpUser, task, between
 
class StudentUser(HttpUser):
    wait_time = between(0.1, 0.5)
 
    def on_start(self):
        """Authenticates a test student on startup and sets the Bearer token."""
        # 1. Login to obtain a live Firebase JWT
        login_payload = {
            "email": "grace.hopper@campus.edu",      # Ensure this student is registered
            "password": "SecurePassword123!"
        }
        response = self.client.post("/api/v1/auth/login", json=login_payload)
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.headers = {
                "Authorization": f"Bearer {token}"
            }
        else:
            print(f"❌ Login failed during Locust startup: {response.text}")
            self.headers = {}
 
    @task(8)
    def view_results(self):
        """80% of traffic: Viewing results (Cache-Aside hit path)."""
        semester = random.choice([1, 2, 3])
        self.client.get(
            f"/api/v1/results/{semester}",
            headers=self.headers,
            name="/api/v1/results/[sem]"
        )
 
    @task(2)
    def initiate_payment(self):
        """20% of traffic: Fee Payment initiation (Atomic Redis lock path)."""
        payload = {
            "amount": 1500.00,
            "purpose": "SEMESTER_FEE"
        }
        headers = {**self.headers, "X-Idempotency-Key": str(uuid.uuid4())}
        self.client.post(
            "/api/v1/payments/initiate",
            json=payload,
            headers=headers,
            name="/api/v1/payments/initiate"
        )