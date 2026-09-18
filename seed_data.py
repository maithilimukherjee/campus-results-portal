import asyncio
from decimal import Decimal
from sqlalchemy.future import select
from app.database import AsyncSessionLocal
from app.models import Student, Teacher, Result

async def seed_mock_data():
    print("Checking and seeding Neon PostgreSQL records...")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 1. Fetch or create Teacher
            teacher_stmt = select(Teacher).where(Teacher.user_uid == "mock_teacher_uid_123")
            teacher = (await session.execute(teacher_stmt)).scalar_one_or_none()
            
            if not teacher:
                teacher = Teacher(
                    user_uid="mock_teacher_uid_123",
                    employee_id="EMP001",
                    full_name="Dr. Alan Turing",
                    department="Computer Science"
                )
                session.add(teacher)
                await session.flush()
                print("Created mock teacher.")
            else:
                print("Mock teacher already exists.")

            # 2. Fetch or create Student
            student_stmt = select(Student).where(Student.user_uid == "mock_student_uid_456")
            student = (await session.execute(student_stmt)).scalar_one_or_none()
            
            if not student:
                student = Student(
                    user_uid="mock_student_uid_456",
                    roll_number="CS2026001",
                    full_name="Grace Hopper",
                    department="Computer Science"
                )
                session.add(student)
                await session.flush()
                print("Created mock student.")
            else:
                print("Mock student already exists.")

            # 3. Add Semester 1 Results if missing
            results_stmt = select(Result).where(
                Result.student_id == student.id,
                Result.semester == 1
            )
            existing_results = (await session.execute(results_stmt)).scalars().all()

            if not existing_results:
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
                print("Created 3 subject results for Semester 1.")
            else:
                print("Semester 1 results already exist.")

        await session.commit()
        print("Database seeding check complete!")

if __name__ == "__main__":
    asyncio.run(seed_mock_data())