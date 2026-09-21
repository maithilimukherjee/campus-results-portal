# Campus Results Portal

🚀 **Live API:** [https://campus-results-portal.onrender.com](https://campus-results-portal.onrender.com)

📖 **Swagger UI:** [https://campus-results-portal.onrender.com/docs](https://campus-results-portal.onrender.com/docs)

A production-grade backend API built for **Result Day** — the single most traffic-intensive day in a college's academic calendar. When results are announced, thousands of students simultaneously rush to check their grades, causing traditional servers to crash. This system is engineered to handle that spike without failure.

---

## Problem Statement

On Result Day, college servers crash due to the massive simultaneous load of students logging in to view their results. Students are locked out at the most critical moment. Additionally, traditional systems block students from viewing results if their fees are pending, and provide no digital process for grade reevaluation.

---

## Solution

A fully async FastAPI backend with:
- **Redis caching** to absorb the Result Day traffic spike
- **4-server load balancing** via nginx to distribute concurrent requests
- **Payment-decoupled result viewing** — fees never block a student from seeing their grades
- **Digital reevaluation workflow** — students can contest grades directly through the portal

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (async) |
| Database | Neon PostgreSQL (via asyncpg) |
| Cache + Lock | Redis |
| Authentication | Firebase Auth (JWT) |
| Load Balancer | nginx |
| Load Testing | Locust |
| ORM | SQLAlchemy 2.0 (async) |

---

## Architecture

```
Client Request
      ↓
nginx (port 80) — Round-robin load balancer
      ↓
┌────┬────┬────┬────┐
W1   W2   W3   W4      ← 4 FastAPI uvicorn workers (ports 8001–8004)
└────┴────┴────┴────┘
      ↓           ↓
 Neon DB       Redis
(persistent)  (cache + lock)
      ↑
 Firebase Auth (JWT verification)
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `students` | Student profiles with current semester tracking |
| `teachers` | Teacher profiles |
| `class_teachers` | Maps a teacher to a semester + department |
| `results` | Subject-wise marks with draft/published and reevaluation status |
| `payments` | Semester fee payment records with idempotency |

---

## API Endpoints

### Auth — `/api/v1/auth`
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/register` | Public | Register a new user in Firebase |
| POST | `/login` | Public | Login and receive JWT token |
| GET | `/me` | Any | Get current user profile |
| POST | `/set-role` | Admin | Assign role and provision DB profile |

### Results — `/api/v1/results`
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/upload-marks` | Teacher | Bulk upload marks as drafts |
| GET | `/{semester}` | Any | View published results (Redis cached) |
| GET | `/{semester}/download` | Any | Download grade card (no payment gate) |
| POST | `/{semester}/request-reevaluation` | Student | Request reevaluation for a subject |
| GET | `/reevaluations/pending` | Teacher | View pending reevaluation requests |
| POST | `/reevaluations/complete` | Teacher | Submit updated marks after reevaluation |

### Payments — `/api/v1/payments`
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/initiate` | Student | Initiate semester fee payment |
| POST | `/callback` | Admin | Update payment status (SUCCESS/FAILED) |

### Admin — `/api/v1/admin`
| Method | Endpoint | Role | Description |
|---|---|---|---|
| POST | `/assign-class-teacher` | Admin | Assign teacher to semester + department |
| POST | `/publish-results` | Admin | Publish draft results to students |
| GET | `/payment-requests` | Admin | View all payment records with filters |
| POST | `/promote-student` | Admin | Promote student to next semester |

---

## Key Engineering Decisions

### 1. Redis Cache-Aside (Result Day Traffic)
Every result view checks Redis first. Only the first request per student per semester hits Neon. Subsequent requests are served from cache with a 24-hour TTL. When results are updated (reevaluation or publish), the cache is forcefully invalidated.

### 2. Payment Never Blocks Results
Viewing results and downloading grade cards has zero payment dependency. Payment is only required for semester promotion. This ensures students always have access to their academic records.

### 3. Idempotent Payments
Payment keys are deterministically generated as `FEE_{year}_{roll_number}_SEM{semester}`. A Redis distributed lock (10-second window) prevents double-click duplicates. Failed payments append an attempt counter so students are never permanently locked out.

### 4. Draft → Publish Workflow
Teachers upload marks as drafts (`is_published=False`). Students cannot see drafts. Admin publishes results for an entire semester + department in one action, making them visible to all students simultaneously.

### 5. Reevaluation Workflow
Students can request reevaluation per subject (one request per subject enforced). The assigned class teacher reviews and submits updated marks. On completion, the student's Redis cache is invalidated so they see the corrected grade card immediately.

### 6. Student Promotion Gates
Promotion checks academics first (no failing grades), then financials (fee paid for next semester). If a student has an F grade, promotion is blocked and a repeat fee is required.

---

## Project Structure

```
campus-results-portal/
├── app/
│   ├── routers/
│   │   ├── admin_router.py       # Admin endpoints
│   │   ├── auth_router.py        # Auth endpoints
│   │   ├── payments_router.py    # Payment endpoints
│   │   └── results_router.py     # Results + reevaluation endpoints
│   ├── auth.py                   # Firebase JWT verification + RBAC
│   ├── config.py                 # Firebase Admin SDK initialization
│   ├── database.py               # Async SQLAlchemy engine + session
│   ├── main.py                   # FastAPI app + router registration
│   ├── models.py                 # SQLAlchemy ORM models
│   └── redis_client.py           # Redis async client
├── .env                          # Environment variables (not committed)
├── .env.example                  # Environment variable template
├── .gitignore
├── init_db.py                    # Creates all tables in Neon PostgreSQL
├── locustfile.py                 # Load testing simulation
├── make_admin.py                 # Promotes a user to admin role
├── requirements.txt
├── seed_admin.py                 # Seeds admin user
├── seed_data.py                  # Seeds mock student, teacher and results
├── seed_student_marks.py         # Seeds additional student marks
└── test_db.py                    # Database connection test
```

---

## Project Setup

### Prerequisites
- Python 3.11+
- Redis server running
- Neon PostgreSQL database
- Firebase project with service account key
- nginx (for load balancing)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd campus-results-portal

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file based on `.env.example`:

```env
apiKey=YOUR_FIREBASE_WEB_API_KEY
FIREBASE_KEY_PATH=serviceAccountKey.json
DATABASE_URL=postgresql://user:password@host/dbname
REDIS_URL=redis://localhost:6379
```

Place your Firebase `serviceAccountKey.json` in the project root.

### Initialize Database

```bash
python init_db.py
```

### Seed Mock Data (Optional)

```bash
python seed_data.py
```

---

## Running the Application

### Single Server (Development)

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Visit `http://127.0.0.1:8000/docs` for Swagger UI.

### 4-Server Load Balanced Setup (Production)

**Step 1 — Start 4 uvicorn workers:**
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
uvicorn app.main:app --host 127.0.0.1 --port 8002
uvicorn app.main:app --host 127.0.0.1 --port 8003
uvicorn app.main:app --host 127.0.0.1 --port 8004
```

**Step 2 — Start nginx:**
```bash
# From nginx directory
nginx.exe
```

Visit `http://localhost/docs` for Swagger UI.

**Stop nginx:**
```bash
taskkill /f /im nginx.exe
```

### nginx Configuration (`conf/nginx.conf`)

```nginx
events {
    worker_connections 1024;
}

http {
    upstream fastapi_backend {
        server 127.0.0.1:8001;
        server 127.0.0.1:8002;
        server 127.0.0.1:8003;
        server 127.0.0.1:8004;
    }

    server {
        listen 80;
        server_name localhost;

        location / {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

---

## Load Testing

```bash
locust -f locustfile.py --host=http://localhost
```

Open `http://localhost:8089`, set number of users and spawn rate.

The locustfile simulates:
- **80% of traffic** — students viewing results (tests Redis cache-aside)
- **20% of traffic** — students initiating payments (tests Redis lock + idempotency)

---

## Roles

| Role | Permissions |
|---|---|
| `unassigned` | Default on registration, no access |
| `student` | View results, download grade card, initiate payment, request reevaluation |
| `teacher` | Upload marks, view and complete reevaluations |
| `admin` | Full access — assign teachers, publish results, manage payments, promote students |

---

## Building a Frontend on Top of This API

This backend is fully REST-compliant and ready to plug into any frontend framework.

### Authentication Flow
- Call `POST /api/v1/auth/login` with email and password
- Store the returned `access_token` (Firebase JWT) in `localStorage` or a cookie
- Attach it to every request as `Authorization: Bearer <token>`
- Use `GET /api/v1/auth/me` to get the logged-in user's role and render the correct dashboard

### Student Dashboard
- `GET /api/v1/results/{semester}` — fetch and display the result card for any semester
- The response includes a `source` field (`CACHE_HIT` or `DATABASE_MISS`) — useful to show a cache status indicator
- `GET /api/v1/results/{semester}/download` — trigger a grade card download
- `POST /api/v1/results/{semester}/request-reevaluation` — show a reevaluation request button per subject
- `POST /api/v1/payments/initiate` — build a fee payment form per semester

### Teacher Dashboard
- `POST /api/v1/results/upload-marks` — build a bulk marks upload form (CSV or manual entry)
- `GET /api/v1/results/reevaluations/pending` — show a list of pending reevaluation requests
- `POST /api/v1/results/reevaluations/complete` — form to submit updated marks per student

### Admin Dashboard
- `POST /api/v1/auth/set-role` — user management panel to assign roles
- `POST /api/v1/admin/assign-class-teacher` — assign teachers to semesters
- `POST /api/v1/admin/publish-results` — one-click publish button per semester + department
- `GET /api/v1/admin/payment-requests` — filterable payment records table
- `POST /api/v1/admin/promote-student` — student promotion panel

### Recommended Frontend Stack
| Layer | Suggestion |
|---|---|
| Framework | React / Next.js |
| HTTP Client | Axios or fetch with interceptors for JWT attachment |
| Auth State | React Context or Zustand to store token and role |
| UI | Tailwind CSS / shadcn/ui |

All endpoints return clean JSON responses and are fully documented at `/docs` via Swagger UI.
