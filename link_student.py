import asyncio
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models import Student

async def link_account(firebase_uid: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = select(Student).where(Student.roll_number == "CS2026001")
            student = (await session.execute(stmt)).scalar_one_or_none()
            if student:
                student.user_uid = firebase_uid
                print(f"linked to Firebase UID: {firebase_uid}")
            else:
                print("❌ Student record CS2026001 not found.")

if __name__ == "__main__":
    # Paste your actual Firebase UID from /api/v1/auth/me here:
    MY_UID = "3eGwlGfWJXNHxbav5fRNoG3njv63"
    asyncio.run(link_account(MY_UID))