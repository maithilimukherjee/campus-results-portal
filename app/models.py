import uuid
import enum
from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, Enum as SQLEnum, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_uid = Column(String, unique=True, nullable=False, index=True)  # Auto-linked Firebase UID
    roll_number = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    department = Column(String, nullable=False)

    results = relationship("Result", back_populates="student", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="student")

class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_uid = Column(String, unique=True, nullable=False, index=True)  # Auto-linked Firebase UID
    employee_id = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    department = Column(String, nullable=False)

    published_results = relationship("Result", back_populates="publisher")

class Result(Base):
    __tablename__ = "results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    published_by_id = Column(UUID(as_uuid=True), ForeignKey("teachers.id"), nullable=True)
    semester = Column(Integer, nullable=False)
    subject_code = Column(String, nullable=False)
    subject_name = Column(String, nullable=False)
    marks_obtained = Column(Numeric(5, 2), nullable=False)
    max_marks = Column(Numeric(5, 2), default=100.0)
    grade = Column(String, nullable=False)

    student = relationship("Student", back_populates="results")
    publisher = relationship("Teacher", back_populates="published_results")

    __table_args__ = (
        UniqueConstraint("student_id", "semester", "subject_code", name="uix_student_semester_subject"),
    )

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship("Student", back_populates="payments")