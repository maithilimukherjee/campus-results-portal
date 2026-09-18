import asyncio
from decimal import Decimal
from app.database import AsyncSessionLocal
from app.models import Student, Teacher, Result

async def seed_mock_data():
    print("Seeding Neon PostgreSQL with sample records...")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 1. Create a sample Teacher
            teacher = Teacher(
                user_uid="mock_teacher_uid_123",
                employee_id="EMP001",
                full_name="Dr. Alan Turing",
                department="Computer Science"
            )
            session.add(teacher)
            await session.flush()

            # 2. Create a sample Student
            student = Student(
                user_uid="mock_student_uid_456",
                roll_number="CS2026001",
                full_name="Grace Hopper",
                department="Computer Science"
            )
            session.add(student)
            await session.flush()

            # 3. Create Semester 1 Results
            results = [
                Result(
                    student_id=student.id,
                    published_by_id=teacher.id,
                    semester=1,
                    subject_code="CS101",
                    subject_name="Data Structures",
                    marks_obtained=Decimal("92.50"),
                    max_marks=Decimal("100.00"),
                    grade="A+"
                ),
                Result(
                    student_id=student.id,
                    published_by_id=teacher.id,
                    semester=1,
                    subject_code="MA101",
                    subject_name="Calculus & Linear Algebra",
                    marks_obtained=Decimal("88.00"),
                    max_marks=Decimal("100.00"),
                    grade="A"
                ),
                Result(
                    student_id=student.id,
                    published_by_id=teacher.id,
                    semester=1,
                    subject_code="PH101",
                    subject_name="Engineering Physics",
                    marks_obtained=Decimal("95.00"),
                    max_marks=Decimal("100.00"),
                    grade="O"
                )
            ]
            session.add_all(results)
            
        await session.commit()
        print("Seeded 1 Teacher, 1 Student, and 3 Subject Results!")

if __name__ == "__main__":
    asyncio.run(seed_mock_data())

