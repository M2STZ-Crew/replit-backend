import { Fragment, useCallback, useEffect, useState } from 'react';

import { StatePanel, StatusChip } from '../ui/index.js';
import RecordedTime from './RecordedTime.jsx';

function Narrative({ text }) {
  return (
    <div className="web-summary-narrative">
      {text.trim().split(/\r?\n\s*\r?\n/).map((paragraph, index) => (
        <p key={index}>
          {paragraph.split(/\r?\n/).map((line, lineIndex) => (
            <Fragment key={lineIndex}>{lineIndex > 0 && <br />}{line}</Fragment>
          ))}
        </p>
      ))}
    </div>
  );
}

// readSummary({ areaId }) supplies a UI snapshot, not a transport contract:
// { state, summary, statusError?, textError? }. No generation action is called.
export default function IncidentSummary({ areaId, readSummary }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({ areaId: null, reader: readSummary, loading: true });
  const reload = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setResult({ areaId, reader: readSummary, loading: true });
    // Read only on explicit summary selection or a failed-read retry; no polling.
    (async () => {
      try {
        if (typeof readSummary !== 'function') throw new Error('A summary reader is required.');
        const snapshot = await readSummary({ areaId });
        const state = snapshot?.state ?? null;
        if (!snapshot || typeof snapshot !== 'object'
            || ![null, 'ready', 'writing', 'unavailable'].includes(state)
            || (snapshot.summary && typeof snapshot.summary.summary_text !== 'string')) {
          throw new Error('The summary could not be read.');
        }
        if (!active) return;
        setResult({
          areaId,
          reader: readSummary,
          loading: false,
          state,
          summary: snapshot.summary || null,
          statusError: snapshot.statusError === true,
          textError: snapshot.textError === true,
        });
      } catch {
        if (active) {
          setResult({
            areaId, reader: readSummary, loading: false,
            state: null, summary: null, statusError: true, textError: true,
          });
        }
      }
    })();
    return () => { active = false; };
  }, [areaId, attempt, readSummary]);

  if (result.areaId !== areaId || result.reader !== readSummary || result.loading) {
    return <StatePanel kind="loading" title="Loading the AI summary" />;
  }

  const { state, summary, statusError, textError } = result;
  const bothFailed = statusError && textError;
  if (bothFailed) {
    return <StatePanel kind="error" title="Could not load the AI summary"
                       description="Try loading the stored summary again."
                       onRetry={reload} />;
  }

  return (
    <section className="web-incident-summary" aria-label="AI summary">
      <header className="web-report-heading">
        <h3>AI summary</h3>
        {state && (
          <StatusChip label={{ ready: 'Ready', writing: 'Being prepared', unavailable: 'Unavailable' }[state] || state}
                      tone={{ ready: 'ok', writing: 'info', unavailable: 'neutral' }[state] || 'neutral'} />
        )}
      </header>
      <p className="web-note">
        This is the incident’s AI summary. It is separate from each team’s filed report.
      </p>
      {state === 'writing' && (
        <StatePanel kind="loading" title="A summary is being prepared"
                    description={summary
                      ? 'The previous summary is shown below. It may not include the latest filed reports.'
                      : 'The latest filed reports are being summarized.'} />
      )}
      {state === 'unavailable' && (
        <StatePanel kind="blocked" title="The latest summary is unavailable"
                    description={summary
                      ? 'A previous summary is shown below. Refer to the filed team reports for the complete record.'
                      : 'The filed team reports remain available.'} />
      )}
      {(statusError || textError) && (
        <StatePanel kind="error"
                    title={statusError ? 'Could not check the latest summary status' : 'Could not load the stored summary history'}
                    description="The available summary is shown below when one was returned."
                    onRetry={reload} />
      )}
      {summary ? (
        <article className="web-summary-record">
          <p className="web-report-meta">Generated <RecordedTime value={summary.generated_at} /></p>
          <Narrative text={summary.summary_text} />
        </article>
      ) : !state && !statusError && !textError ? (
        <StatePanel kind="empty" title="No stored summary"
                    description="Read the filed team reports for this incident." />
      ) : state === 'ready' ? (
        <StatePanel kind="empty" title="No summary text was returned"
                    description="The filed team reports remain available." />
      ) : null}
    </section>
  );
}
