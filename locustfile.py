import uuid
import random
from locust import HttpUser, task, between
 
class StudentUser(HttpUser):
    wait_time = between(0.1, 0.5)
 
    def on_start(self):
        """Authenticates a test student on startup and sets the Bearer token."""
        login_payload = {
            "email": "grace.hopper@campus.edu",
            "password": "SecurePassword123!"
        }
        # Note: If your FastAPI uses OAuth2PasswordRequestForm, this should be data=login_payload, not json=
        response = self.client.post("/api/v1/auth/login", json=login_payload)
        if response.status_code == 200:
            token = response.json().get("access_token")
            self.headers = {
                "Authorization": f"Bearer {token}"
            }
        else:
            print(f"❌ Login failed during Locust startup: {response.text}")
            self.headers = {}
 
    @task(7)
    def view_results(self):
        """70% of traffic: Viewing results (Testing Redis Cache-Aside)."""
        semester = random.choice([1, 2, 3])
        self.client.get(
            f"/api/v1/results/{semester}",
            headers=self.headers,
            name="/api/v1/results/[sem]"
        )
 
    @task(2)
    def initiate_payment(self):
        """20% of traffic: Fee Payment (Testing Redis Lock & Idempotency)."""
        payload = {
            "amount": 1500.00,
            "purpose": "SEMESTER_FEE",
            "semester": random.choice([2, 3, 4]) # ⚡ MANDATORY FIX: Added semester
        }
        headers = {**self.headers, "X-Idempotency-Key": str(uuid.uuid4())}
        self.client.post(
            "/api/v1/payments/initiate",
            json=payload,
            headers=headers,
            name="/api/v1/payments/initiate"
        )
 
    @task(1)
    def request_reevaluation(self):
        """10% of traffic: Reevaluation (Testing PostgreSQL constraints)."""
        semester = random.choice([1, 2, 3])
        payload = {
            "subject_code": random.choice(["CS101", "CS102", "MA101"])
        }
        self.client.post(
            f"/api/v1/results/{semester}/request-reevaluation",
            json=payload,
            headers=self.headers,
            name="/api/v1/results/[sem]/request-reevaluation"
        )