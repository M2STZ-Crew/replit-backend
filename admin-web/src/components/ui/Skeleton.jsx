/* Placeholders in the shape of what is loading (5 Nov 2026 issue list, 1.6):
 * grey blocks where the table rows, cards or the incident will be, with a soft
 * highlight sweeping across them, instead of a line of "Loading…" text. The
 * page keeps its layout while it loads, so nothing jumps when the data comes.
 *
 * Purely visual: it is aria-hidden, and whoever shows it says what is loading
 * in words a screen reader can hear (StatePanel's status line does). Under
 * prefers-reduced-motion the sweep stops (index.css). */

function Line({ width = '100%', height = 12, className = '' }) {
  return <span className={`rpl-skel rpl-skel-line ${className}`.trim()} style={{ width, height }} />;
}

function TableShape({ rows }) {
  return (
    <div className="rpl-skel-table">
      <div className="rpl-skel-row rpl-skel-row--head">
        <Line width="18%" height={10} />
        <Line width="26%" height={10} />
        <Line width="16%" height={10} />
        <Line width="12%" height={10} />
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div className="rpl-skel-row" key={i}>
          <span className="rpl-skel rpl-skel-plate" />
          <div className="rpl-skel-stack">
            <Line width={`${52 + ((i * 17) % 30)}%`} height={13} />
            <Line width={`${34 + ((i * 11) % 24)}%`} height={10} />
          </div>
          <Line width="14%" height={22} className="rpl-skel-pill" />
        </div>
      ))}
    </div>
  );
}

function CardsShape({ rows }) {
  return (
    <div className="rpl-skel-cards">
      {Array.from({ length: rows }, (_, i) => (
        <div className="rpl-skel-card" key={i}>
          <span className="rpl-skel rpl-skel-media" />
          <Line width="62%" height={14} />
          <Line width="88%" height={10} />
          <Line width="40%" height={10} />
        </div>
      ))}
    </div>
  );
}

function DetailShape({ rows }) {
  return (
    <div className="rpl-skel-detail">
      <Line width="42%" height={22} />
      <Line width="64%" height={12} />
      <div className="rpl-skel-figures">
        <span className="rpl-skel rpl-skel-figure" />
        <span className="rpl-skel rpl-skel-figure" />
        <span className="rpl-skel rpl-skel-figure" />
      </div>
      <span className="rpl-skel rpl-skel-media rpl-skel-media--wide" />
      <TableShape rows={rows} />
    </div>
  );
}

function LinesShape({ rows }) {
  return (
    <div className="rpl-skel-lines">
      {Array.from({ length: rows }, (_, i) => (
        <Line key={i} width={i === rows - 1 ? '58%' : `${88 + ((i * 7) % 12)}%`} />
      ))}
    </div>
  );
}

const SHAPES = { table: TableShape, cards: CardsShape, detail: DetailShape, lines: LinesShape };

export default function Skeleton({ shape = 'table', rows = 6, className = '' }) {
  const Shape = SHAPES[shape] || TableShape;
  return (
    <div className={`rpl-skeleton rpl-skeleton--${shape} ${className}`.trim()} aria-hidden="true"
         data-testid="skeleton">
      <Shape rows={rows} />
    </div>
  );
}
