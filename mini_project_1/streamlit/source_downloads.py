"""출처 PDF를 클릭할 때만 읽어 다운로드한다."""
from functools import partial
from pathlib import Path

PDF_DIR = Path(__file__).resolve().parent.parent / "files"


def read_source_pdf(filename, pdf_dir=PDF_DIR):
    root = Path(pdf_dir).resolve()
    path = (root / filename).resolve()
    if path.parent != root or path.suffix.lower() != ".pdf":
        raise ValueError("출처 PDF 경로가 올바르지 않습니다.")
    return path.read_bytes()


def prepare_downloads(sources, pdf_dir=PDF_DIR):
    """파일 존재만 확인한다. 반환한 함수 호출 전에는 PDF 본문을 읽지 않는다."""
    root = Path(pdf_dir).resolve()
    seen = set()
    downloads = []
    for source in sources:
        filename = source.get("source")
        if not isinstance(filename, str) or not filename or filename in seen:
            continue
        seen.add(filename)
        path = (root / filename).resolve()
        if path.parent != root or path.suffix.lower() != ".pdf" or not path.is_file():
            continue
        downloads.append((path.name, partial(read_source_pdf, filename, root)))
    return downloads


def render_source_downloads(sources, key_prefix):
    import streamlit as st

    for index, (filename, reader) in enumerate(prepare_downloads(sources)):
        st.download_button(f"{filename} 다운로드", data=reader, file_name=filename,
                           mime="application/pdf", key=f"{key_prefix}_pdf_{index}",
                           on_click="ignore", icon=":material/download:")
