from fastapi import FastAPI
from app.routers import auth_router, results_router, payments_router, admin_router
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="Result-Day Digital Campus Platform API",
    version="1.0.0",
    description="Decoupled SOA Backend for Result Viewing and Payment Services"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows requests from any frontend origin during development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(auth_router.router)
app.include_router(results_router.router)
app.include_router(payments_router.router)
app.include_router(admin_router.router)


@app.get("/")
def health_check():
    return {"status": "healthy", "service": "API Gateway"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
