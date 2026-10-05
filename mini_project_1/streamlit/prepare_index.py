"""최초 인덱스 준비. 기존 컬렉션을 삭제하거나 재구축하지 않는다."""
import base64
import hashlib
import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chromadb
from filelock import FileLock
from langchain_chroma import Chroma
from langchain_classic.storage import LocalFileStore
from langchain_classic.storage._lc_store import create_kv_docstore
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# 서비스가 시작된 뒤에는 다른 세션에서도 최초 적재 분기로 들어가지 않는다.
_STARTED = {}
_START_LOCK = threading.Lock()
PDF_CONFIGS = {1: "pymupdf_markdown", 2: "vlm", 3: "vlm", 4: "vlm",
               5: "vlm", 6: "vlm", 7: "vlm", 8: "pymupdf_markdown"}
VLM_PROMPT = """아래는 같은 PDF 페이지의 두 가지 정보다.
(A) 페이지 이미지 - 표의 행/열 구조와 화면 배치를 여기서 읽는다.
(B) PDF 내부 텍스트 레이어 - 글자 표기(철자)가 정확하다. 단 순서가 뒤섞여 구조 정보는 없다.

규칙:
1. 구조는 (A)에서, 글자 표기는 (B)에서 가져온다. (B)에 있는 단어는 (B)의 철자를 그대로 쓰고
   이미지로 읽은 추측 철자로 덮어쓰지 않는다. ('탭/법', '뎁스/탑스', '日/타' 등 혼동 금지)
2. 표가 있으면 마크다운 파이프 테이블로 출력한다.
   - 열 개수는 데이터 행을 기준으로 정한다. 머리글이 없는 열(하위 구분 등)이 있으면
     헤더에 이름을 새로 지어 붙여서 열을 늘린다. 값을 지워 열 수를 맞추는 것은 절대 금지.
   - 세로로 병합된 셀은 이미지에서 그 셀이 세로로 덮고 있는 행 범위를 정확히 확인해서
     해당하는 모든 행에 값을 반복해 채운다. 그룹 경계를 틀리지 마라.
3. 표 아래에 `#### 표 행 풀어쓰기` 를 붙이고, 각 데이터 행을 한 문장씩 쓴다.
   모든 열의 값이 문장 안에 빠짐없이 들어가야 하고, 데이터 행 수와 문장 수가 같아야 한다.
4. 제목은 #, 소제목은 ##. 화면 캡처/차트/흐름도 안의 글자도 모두 옮기고,
   절차 흐름도는 "1단계 -> 2단계" 형태로 순서를 풀어 쓴다.
5. 금액·기간·수수료율·URL·날짜는 원문 표기 그대로 옮긴다.
6. 해설/요약/추측 금지. 페이지에 실제로 적힌 내용만 출력한다.

=== (B) 텍스트 레이어 ===
{layer}
=== 끝 ==="""


# PDF를 파싱하고 본문을 추출해 검색용 청크로 분할한다.
def load_and_split_documents(settings):
    import pymupdf
    from langchain_community.document_loaders import PyMuPDFLoader
    from openai import OpenAI

    paths = sorted(Path(settings["pdf_dir"]).glob("*.pdf"))
    if not paths:
        raise ValueError("인덱스 최초 준비에 필요한 PDF가 files/에 없습니다.")
    cache = Path(settings["cache_dir"])
    cache.mkdir(parents=True, exist_ok=True)
    client = OpenAI()

    # PDF 페이지를 VLM으로 파싱하거나 저장된 파싱 결과를 재사용한다.
    def parse_page(path, number):
        with pymupdf.open(path) as pdf:
            page = pdf[number]
            layer = page.get_text("text")
            model = settings["lower_model"]
            if len(layer.strip()) < 100:
                model = settings["model"]
            else:
                try:
                    if page.find_tables().tables:
                        model = settings["model"]
                except Exception:
                    pass
            key = hashlib.md5(f"{path.name}|{number}|{model}|200|v2".encode()).hexdigest()[:16]
            target = cache / f"{key}.md"
            if target.exists():
                return target.read_text(encoding="utf-8")
            png = page.get_pixmap(dpi=200).tobytes("png")
        response = client.chat.completions.create(model=model, messages=[{
            "role": "user", "content": [
                {"type": "text", "text": VLM_PROMPT.format(layer=layer or "(텍스트 레이어 없음 - 이미지만으로 판독)")},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(png).decode(), "detail": "high"}},
            ]}])
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise ValueError(f"PDF 파싱 결과가 비어 있습니다: {path.name} p.{number + 1}")
        target.write_text(text, encoding="utf-8")
        return text

    raw = []
    for path in paths:
        match = re.match(r"\s*(\d+)", path.name)
        if not match or int(match.group(1)) not in PDF_CONFIGS:
            raise ValueError(f"문서별 로더 설정이 없습니다: {path.name}")
        loader = PDF_CONFIGS[int(match.group(1))]
        if loader == "pymupdf_markdown":
            docs = PyMuPDFLoader(str(path), mode="page", extract_tables="markdown").load()
            raw.extend(Document(page_content=doc.page_content,
                metadata={"source": path.name, "page": doc.metadata.get("page", i) + 1, "loader": loader})
                for i, doc in enumerate(docs) if doc.page_content.strip())
        else:
            with pymupdf.open(path) as pdf:
                count = pdf.page_count
            with ThreadPoolExecutor(max_workers=8) as executor:
                texts = list(executor.map(lambda i: parse_page(path, i), range(count)))
            raw.extend(Document(page_content=text, metadata={"source": path.name, "page": i + 1,
                       "loader": loader}) for i, text in enumerate(texts) if text.strip())

    last = {}
    for doc in raw:
        last[doc.metadata["source"]] = max(last.get(doc.metadata["source"], 0), doc.metadata["page"])
    body = []
    for doc in raw:
        text = doc.page_content.strip()
        head = "\n".join(text.splitlines()[:6])
        is_toc = (re.search(r"(목차|차례|CONTENTS|INDEX)", head, re.I)
                  or len(re.findall(r"\.{5,}\s*\d+\s*P", text, re.I)) >= 2
                  or len(re.findall(r"\b\d+\s*P\b", text, re.I)) >= 4)
        is_cover = (len(re.sub(r"\s+", "", text)) < 100
                    and (doc.metadata["page"] <= 2 or doc.metadata["page"] == last[doc.metadata["source"]]))
        if not is_toc and not is_cover:
            body.append(doc)
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")], strip_headers=False)
    headers = []
    for doc in body:
        for section in header_splitter.split_text(doc.page_content):
            section.metadata = {**doc.metadata, **section.metadata}
            headers.append(section)
    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150,
                                              separators=["\n\n", "\n", " ", ""])
    chunks = [doc for doc in splitter.split_documents(headers) if len(doc.page_content.strip()) >= 30]
    if not chunks:
        raise ValueError("최초 적재할 본문 청크가 없습니다.")
    return headers, chunks


# 인덱스를 검증하고 서비스 시작 전에 누락된 저장소만 최초 준비한다.
def ensure_indexes(settings):
    path = Path(settings["chroma_path"])
    parent_path = Path(settings["parent_path"])
    key = str(path.resolve())
    specification = {"embedding": settings["embedding_model"],
        "parent_size": settings["parent_size"], "parent_overlap": settings["parent_overlap"],
        "child_size": settings["child_size"], "child_overlap": settings["child_overlap"]}
    signature = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    marker = path.parent / (path.name + ".initializing")
    with _START_LOCK:
        if key in _STARTED:
            started = _STARTED[key]
            # 읽기 전용 SQLite 연결은 다른 연결의 DB 변경을 감지한다.
            if started["signature"] != signature or not (path / "chroma.sqlite3").exists():
                raise ValueError("운영 중 인덱스 또는 설정이 변경되었습니다. 앱을 중단하고 외부에서 준비하세요.")
            version = started["monitor"].execute("PRAGMA data_version").fetchone()[0]
            parent_snapshot = tuple(sorted((str(f.relative_to(parent_path)), f.stat().st_size, f.stat().st_mtime_ns)
                                          for f in parent_path.rglob("*") if f.is_file()))
            if version != started["version"] or parent_snapshot != started["parents"]:
                raise ValueError("운영 중 저장소 변경이 감지되었습니다. 앱을 중단하고 외부에서 처리하세요.")
            return

        # 프로세스 간 잠금도 획득한 후 상태를 읽어 중복 최초 적재를 막는다.
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path.parent / (path.name + ".startup.lock")), timeout=300):
            if marker.exists():
                raise ValueError("이전 최초 구축이 완료되지 않았습니다. 앱 외부에서 저장소를 확인하세요.")
            client = chromadb.PersistentClient(path=str(path))
            names = {item.name for item in client.list_collections()}
            base_name, child_name = settings["base_collection"], settings["child_collection"]
            base = client.get_collection(base_name) if base_name in names else None
            child = client.get_collection(child_name) if child_name in names else None
            has_parents = parent_path.exists() and any(f.is_file() for f in parent_path.rglob("*"))
            if (base is not None and base.count() == 0) or (child is not None and child.count() == 0):
                raise ValueError("빈 컬렉션은 불완전한 적재입니다. 앱 외부에서 준비하세요.")
            if (child is not None) != bool(has_parents) or (base is None and child is not None):
                raise ValueError("BASE·부모·자식 저장소가 불완전합니다. 앱 외부에서 준비하세요.")
            if base is not None:
                metadata = base.metadata or {}
                if metadata.get("embedding_model", settings["embedding_model"]) != settings["embedding_model"]:
                    raise ValueError("BASE 임베딩 설정이 다릅니다. 앱 외부에서 준비하세요.")
                if metadata.get("chunk_size", 900) != 900 or metadata.get("chunk_overlap", 150) != 150:
                    raise ValueError("BASE 청킹 설정이 다릅니다. 앱 외부에서 준비하세요.")
                expected_dimension = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072,
                                      "text-embedding-ada-002": 1536}.get(settings["embedding_model"])
                vectors = base.get(limit=1, include=["embeddings"])["embeddings"]
                if expected_dimension and len(vectors[0]) != expected_dimension:
                    raise ValueError("BASE 임베딩 차원이 다릅니다. 앱 외부에서 준비하세요.")

            if child is None:
                # 파싱 실패는 인덱스를 쓰기 전에 전달한다. 적재 시작 이후에는 표식을 남긴다.
                headers, chunks = load_and_split_documents(settings)
                embeddings = OpenAIEmbeddings(model=settings["embedding_model"])
                marker.write_text("최초 적재 진행 중", encoding="utf-8")
                if base is None:
                    base_store = Chroma(client=client, collection_name=base_name, embedding_function=embeddings,
                                        collection_metadata={"embedding_model": settings["embedding_model"],
                                                             "chunk_size": 900, "chunk_overlap": 150})
                    for start in range(0, len(chunks), 128):
                        batch = chunks[start:start + 128]
                        ids = [hashlib.sha256(json.dumps({"text": d.page_content, "metadata": d.metadata},
                               ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest() for d in batch]
                        base_store.add_documents(batch, ids=ids)
                    base = client.get_collection(base_name)
                parent_documents = RecursiveCharacterTextSplitter(chunk_size=settings["parent_size"],
                    chunk_overlap=settings["parent_overlap"]).split_documents(headers)
                child_splitter = RecursiveCharacterTextSplitter(chunk_size=settings["child_size"],
                    chunk_overlap=settings["child_overlap"])
                parent_map, child_map = {}, {}
                for parent in parent_documents:
                    pid = hashlib.sha256(json.dumps({"text": parent.page_content, "metadata": parent.metadata},
                        ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
                    parent_map[pid] = parent
                    for doc in child_splitter.split_documents([parent]):
                        doc.metadata = {**doc.metadata, "parent_id": pid, "index_signature": signature}
                        cid = hashlib.sha256(json.dumps({"text": doc.page_content, "metadata": doc.metadata},
                            ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
                        child_map[cid] = doc
                if not child_map:
                    raise ValueError("적재할 자식 문서가 없습니다.")
                parents = create_kv_docstore(LocalFileStore(str(parent_path)))
                parents.mset(list(parent_map.items()))
                child_store = Chroma(client=client, collection_name=child_name, embedding_function=embeddings)
                entries = list(child_map.items())
                for start in range(0, len(entries), 128):
                    batch = entries[start:start + 128]
                    child_store.add_documents([doc for _, doc in batch], ids=[cid for cid, _ in batch])
                child = client.get_collection(child_name)

            # 노트북과 동일한 설정 서명·부모 원문 ID 연결 검사.
            saved = child.get(include=["metadatas"])
            if any(not m or m.get("index_signature") != signature or not m.get("parent_id")
                   for m in saved["metadatas"]):
                raise ValueError("Parent Document 인덱스 설정이 다릅니다. 앱 외부에서 준비하세요.")
            ids = list(dict.fromkeys(m["parent_id"] for m in saved["metadatas"]))
            parents = create_kv_docstore(LocalFileStore(str(parent_path))).mget(ids)
            for pid, doc in zip(ids, parents):
                if doc is None:
                    raise ValueError("부모 문서가 누락되었습니다. 앱 외부에서 준비하세요.")
                actual = hashlib.sha256(json.dumps({"text": doc.page_content, "metadata": doc.metadata},
                    ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
                if pid != actual:
                    raise ValueError("부모 문서와 자식 연결이 다릅니다. 앱 외부에서 준비하세요.")
            if marker.exists():
                marker.unlink()  # 이 실행이 만든 최초 적재 표식만 정상 완료 후 해제한다.
            monitor = sqlite3.connect(f"file:{(path / 'chroma.sqlite3').resolve()}?mode=ro", uri=True,
                                      check_same_thread=False)
            _STARTED[key] = {"signature": signature, "monitor": monitor,
                "version": monitor.execute("PRAGMA data_version").fetchone()[0],
                "parents": tuple(sorted((str(f.relative_to(parent_path)), f.stat().st_size, f.stat().st_mtime_ns)
                                        for f in parent_path.rglob("*") if f.is_file()))}


if __name__ == "__main__":
    from rag_config import load_settings
    ensure_indexes(load_settings())
    print("인덱스 준비 완료: 기존 호환 인덱스는 재사용했습니다.")
