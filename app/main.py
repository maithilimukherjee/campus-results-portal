from fastapi import FastAPI
from app.routers import auth_router

app = FastAPI(
    title="Result-Day Digital Campus Platform API",
    version="1.0.0",
    description="Decoupled SOA Backend for Result Viewing and Payment Services"
)
# Register Routers
app.include_router(auth_router.router)

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "API Gateway"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
