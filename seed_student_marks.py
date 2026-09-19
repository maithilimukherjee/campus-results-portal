import asyncio
from decimal import Decimal
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models import Student, Result

async def seed_current_student():
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Find the most recently created student profile
            stmt = select(Student).order_by(Student.id.desc())
            student = (await session.execute(stmt)).scalars().first()
            
            if not student:
                print("No student found.")
                return

            print(f"Seeding results for student: {student.full_name} ({student.roll_number})")

            results = [
                Result(
                    student_id=student.id,
                    semester=1,
                    subject_code="CS101",
                    subject_name="Data Structures",
                    marks_obtained=Decimal("94.00"),
                    grade="A+"
                ),
                Result(
                    student_id=student.id,
                    semester=1,
                    subject_code="MA101",
                    subject_name="Linear Algebra",
                    marks_obtained=Decimal("89.00"),
                    grade="A"
                )
            ]
            session.add_all(results)
            print("Successfully seeded Semester 1 results!")

if __name__ == "__main__":
    asyncio.run(seed_current_student())