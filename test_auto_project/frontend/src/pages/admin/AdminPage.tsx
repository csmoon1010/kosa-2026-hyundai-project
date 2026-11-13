import { Navigate, useParams } from 'react-router';

import { Card } from '../../components/Card';
import { Spinner } from '../../components/Spinner';
import { useAdminData, type AdminData } from './adminData';
import styles from './admin.module.css';
import { BaselineCard } from './BaselineCard';
import { DocGrid } from './docs/DocGrid';
import { DomainTable } from './DomainTable';
import { EnvCard } from './EnvCard';
import { RealCard } from './RealCard';
import { RuleCard } from './rules/RuleCard';
import { GraphEditor } from './graph/GraphEditor';
import { DOMAINS, REAL_DOM, type Scope } from './scope';
import { ScopeBar } from './ScopeBar';
import { SwaggerAll } from './SwaggerAll';

const SCOPES = new Set<string>(['all', ...DOMAINS.map(([d]) => d)]);

/** 관리자 메뉴 — /admin/all 전사, /admin/order · goods · logistics 도메인 */
export default function AdminPage() {
  const { scope = 'all' } = useParams();
  const a = useAdminData();
  if (!SCOPES.has(scope)) return <Navigate to="/admin/all" replace />;
  const s = scope as Scope;
  return (
    <>
      <ScopeBar a={a.ready ? a : null} scope={s} />
      {!a.ready ? (
        a.error ? (
          <p className="nodata">관리자 화면 데이터를 불러오지 못했어요: {a.error.message}</p>
        ) : (
          <Spinner block label="관리자 화면 데이터 불러오는 중" />
        )
      ) : s === 'all' ? (
        <AllScope a={a} />
      ) : (
        <DomainScope a={a} dom={s} />
      )}
    </>
  );
}

function AllScope({ a }: { a: AdminData }) {
  return (
    <div className={styles.grid}>
      <RealCard a={a} />
      <DomainTable a={a} />
      <RuleCard a={a} place="am" dom={null} />
      <SwaggerAll a={a} />
      <DocGrid a={a} dom={null} />
      <EnvCard a={a} />
    </div>
  );
}

function DomainScope({ a, dom }: { a: AdminData; dom: string }) {
  return (
    <div className={styles.grid}>
      <Card className={styles.wide}>
        <GraphEditor dom={REAL_DOM[dom]!} />
      </Card>
      <DocGrid key={dom} a={a} dom={dom} />
      <RuleCard key={`rule-${dom}`} a={a} place="ov" dom={dom} />
      <BaselineCard key={`bl-${dom}`} a={a} dom={dom} />
    </div>
  );
}
