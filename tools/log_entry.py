from datetime import datetime

from tools.health_schema import SymptomLog, Severity
from db.engine import SessionLocal, Base, engine
from db.models import SymptomLogORM

# Ensure tables exist
Base.metadata.create_all(engine)


def tool_log(text: str, user_id: str) -> str:
    """Persist a free-form symptom description.

    Parameters
    ----------
    text : str
        Description provided by the user.
    user_id : str
        Identifier for the submitting user.
    """
    entry = SymptomLog(
        symptom=text,
        severity=Severity.none,
        started_at=datetime.utcnow(),
        notes=f"user:{user_id}",
    )

    with SessionLocal() as db:
        orm_entry = SymptomLogORM(**entry.model_dump())
        db.add(orm_entry)
        db.commit()
        db.refresh(orm_entry)

    return f"Logged entry with id: {orm_entry.id}"
