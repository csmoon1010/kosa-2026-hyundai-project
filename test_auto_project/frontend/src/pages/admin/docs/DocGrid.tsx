import { useState } from 'react';

import { Card } from '../../../components/Card';
import type { AdminData } from '../adminData';
import styles from '../admin.module.css';
import { DocModal } from './DocModal';
import { DOCS, useDoc, type DocId } from './registry';

/** 데이터 조회 — 문서 8종 타일, 누르면 팝업 */
export function DocGrid({ a, dom }: { a: AdminData; dom: string | null }) {
  const doc = useDoc(a);
  const [open, setOpen] = useState<DocId | null>(null);
  return (
    <Card className={styles.wide} title="데이터 조회">
      <div className={styles.docgrid}>
        {DOCS.map(([id, name, role], k) => {
          const result = doc(id, dom);
          const cnt = result === null ? '…' : result.count;
          return (
            <button
              key={id}
              type="button"
              className={`${styles.doctile} ${cnt ? '' : styles.emptyDoc}`}
              onClick={() => setOpen(id)}
            >
              <span className={styles.no}>{k + 1}</span>
              <b>{name}</b>
              <span>{role}</span>
              <em>{cnt || '해당 없음'}</em>
            </button>
          );
        })}
      </div>
      {open && <DocModal a={a} first={open} dom={dom} onClose={() => setOpen(null)} />}
    </Card>
  );
}
