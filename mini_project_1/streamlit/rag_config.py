"""환경 설정과 경로. 비밀값은 반환 설정에 포함하지 않는다."""
import os
from pathlib import Path

from dotenv import load_dotenv


# 환경변수를 읽고 모델 설정과 데이터 경로를 준비한다.
def load_settings():
    project = Path(__file__).resolve().parent.parent
    exercise = project.parent.parent
    load_dotenv(exercise / ".env", override=False)
    required = ("OPENAI_API_KEY", "OPENAI_DEFAULT_MODEL", "OPENAI_LOWER_MODEL", "OPENAI_EMBEDDING_MODEL")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("필수 환경변수를 설정하세요: " + ", ".join(missing))
    return {
        "model": os.environ["OPENAI_DEFAULT_MODEL"],
        "lower_model": os.environ["OPENAI_LOWER_MODEL"],
        "embedding_model": os.environ["OPENAI_EMBEDDING_MODEL"],
        "pdf_dir": str(project / "files"),
        "cache_dir": str(project / "md_cache"),
        "chroma_path": str(project / "chroma_db"),
        "parent_path": str(project / "parent_document_store"),
        "base_collection": "langchain",
        "child_collection": "parent_document_children",
        "k": 6, "wide": 12, "threshold": 0.8,
        "parent_size": 1500, "parent_overlap": 0,
        "child_size": 450, "child_overlap": 75,
        "history_max_turns": 6, "history_max_tokens": 4000,
    }
