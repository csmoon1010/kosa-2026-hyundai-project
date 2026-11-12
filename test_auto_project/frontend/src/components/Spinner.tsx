import styles from './Spinner.module.css';

interface Props {
  /** 화면 읽기 프로그램이 읽는 이름 */
  label?: string;
  size?: 'normal' | 'small';
  /** 결과 자리를 채우는 큰 표시 (지금 .loading) */
  block?: boolean;
}

export function Spinner({ label = '불러오는 중', size = 'normal', block = false }: Props) {
  const spin = (
    <span
      className={`${styles.spinner} ${size === 'small' ? styles.small : ''}`}
      role="status"
      aria-label={label}
    />
  );
  return block ? <div className={styles.block}>{spin}</div> : spin;
}
