import { useState } from 'react';

import { usePreprocessing } from '../../../api/queries';
import { Modal } from '../../../components/Modal';
import { Spinner } from '../../../components/Spinner';
import type { AdminData } from '../adminData';
import styles from '../admin.module.css';
import { DOM_LABEL, REAL_DOM } from '../scope';
import { DOMAIN_NAMES, preHelpers, type ArtifactFilter } from './docsPre';
import { BASE_DOCS, DOCS, PRE_DOCS, isPre, type DocId } from './registry';

// 필터는 문서 · 범위마다 기억한다 (팝업을 닫았다 열어도)
const remembered = new Map<string, Required<ArtifactFilter>>();

/** 데이터 조회 팝업 — 위에 8종 탭, 전처리 4종은 도메인 · document · api_id 필터 */
export function DocModal({
  a,
  first,
  dom,
  onClose,
}: {
  a: AdminData;
  first: DocId;
  dom: string | null;
  onClose: () => void;
}) {
  const [id, setId] = useState<DocId>(first);
  const name = DOCS.find((d) => d[0] === id)![1];
  return (
    <Modal wide eyebrow={`데이터 조회 · ${dom ? DOM_LABEL[dom] : '전사'}`} title={name} onClose={onClose}>
      <div className={styles.docstrip} role="tablist">
        {DOCS.map(([k, n], i) => (
          <button key={k} type="button" role="tab" aria-current={k === id} onClick={() => setId(k)}>
            {i + 1} {n}
          </button>
        ))}
      </div>
      {isPre(id) ? <PreDocBody key={id} a={a} id={id} dom={dom} /> : BASE_DOCS[id](a, dom).body}
    </Modal>
  );
}

function PreDocBody({ a, id, dom }: { a: AdminData; id: keyof typeof PRE_DOCS; dom: string | null }) {
  const pre = usePreprocessing();
  const key = `${id}:${dom || 'all'}`;
  const [filter, setFilterState] = useState<Required<ArtifactFilter>>(
    () => remembered.get(key) ?? { domain: (dom && REAL_DOM[dom]) || '', document: '', api: '' },
  );
  const setFilter = (f: Required<ArtifactFilter>) => {
    remembered.set(key, f);
    setFilterState(f);
  };
  if (!pre.data)
    return pre.isError ? (
      <p className="note">{pre.error.message}</p>
    ) : (
      <Spinner block label="전처리 산출물 불러오는 중" />
    );
  const data = pre.data.preprocessing;
  const h = preHelpers(data, a);
  const entries = h.apis(null);
  const domains = [...new Set(entries.map(([sid]) => h.apiDomain(sid)))].sort();
  const domain = filter.domain && domains.includes(filter.domain) ? filter.domain : '';
  const domainEntries = entries.filter(([sid]) => !domain || h.apiDomain(sid) === domain);
  const documents = [...new Set(domainEntries.map(([sid, c]) => h.documentId(sid, c)))].sort();
  const document = filter.document && documents.includes(filter.document) ? filter.document : '';
  const candidates = domainEntries.filter(([sid, c]) => !document || h.documentId(sid, c) === document);
  const api = filter.api && candidates.some(([sid]) => sid === filter.api) ? filter.api : '';
  const result = PRE_DOCS[id](data, a, dom, { domain, document, api });
  return (
    <>
      <div className={styles.artifactFilters}>
        <label>
          도메인
          <select
            aria-label="도메인 필터"
            value={domain}
            onChange={(e) => setFilter({ domain: e.target.value, document, api })}
          >
            <option value="">도메인 전체</option>
            {domains.map((v) => (
              <option key={v} value={v}>
                {DOMAIN_NAMES[v] || v} ({v})
              </option>
            ))}
          </select>
        </label>
        <label>
          document
          <select
            aria-label="document 필터"
            value={document}
            onChange={(e) => setFilter({ domain, document: e.target.value, api })}
          >
            <option value="">document 전체</option>
            {documents.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          api_id
          <select
            aria-label="api_id 필터"
            value={api}
            onChange={(e) => setFilter({ domain, document, api: e.target.value })}
          >
            <option value="">api_id 전체</option>
            {candidates
              .slice()
              .sort(([, x], [, y]) => x.apiId.localeCompare(y.apiId))
              .map(([sid, c]) => (
                <option key={sid} value={sid}>
                  {c.apiId} · {h.apiName(sid, c)}
                </option>
              ))}
          </select>
        </label>
      </div>
      <p className="note" role="status" aria-live="polite">
        {result.count}
      </p>
      <div>{result.body}</div>
    </>
  );
}
