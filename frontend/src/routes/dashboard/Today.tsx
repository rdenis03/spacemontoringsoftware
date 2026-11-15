/**
 * Today: one status card (level, score, a score meter on the level bands,
 * change vs yesterday), the contributors as a grouped list, and the action
 * cards with their steps as a checklist.
 */
import { useState } from "react";
import { api } from "../../api/client";
import type { ActionCard, Anomaly, Contributor, DayResult, RiskAssessment } from "../../api/types";
import { Frame } from "../../components/Frame";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelTag } from "../../components/LevelTag";
import { NormalBand } from "../../components/NormalBand";
import { LoadError, Loading, PartialNote } from "../../components/StateMessage";
import { formatClock, formatNumber, formatValue, humanize, signedNumber, withUnit } from "../../lib/format";
import { levelBands, levelColor, levelCopy, levelForScore, levelInk } from "../../lib/levels";
import type { AsyncState } from "../../lib/useAsync";
import { useAsync } from "../../lib/useAsync";
import { useRegistry } from "../../state/registry-context";

export default function Today({
  status,
  astronautId,
  freshness,
}: {
  status: AsyncState<DayResult>;
  astronautId: string;
  freshness: string;
}) {
  // The previous assessment gives "change vs yesterday".
  const history = useAsync((signal) => api.assessments(astronautId, signal), [astronautId, freshness], {
    enabled: Boolean(astronautId),
  });

  if (status.error) return <LoadError error={status.error} retry={status.reload} what="assessment" />;
  if (!status.data) return <Loading what="today's status" />;

  const result = status.data;
  const assessment = result.assessment;
  if (!assessment) {
    return (
      <div className="today">
        <PartialNote errors={result.errors ?? []} />
        <LoadError error={new Error("The scorer did not produce a result for this day.")} what="score for this day" />
      </div>
    );
  }
  const previous = previousAssessment(history.data, assessment.assessed_at);

  return (
    <div className="today">
      <StatusCard result={result} previous={previous} />
      <Contributors contributors={assessment.contributors ?? []} anomalies={result.anomalies ?? []} score={assessment.score} />
      <div className="today__actions">
        <ActionsPanel key={`${result.astronaut_id}-${result.as_of}`} cards={result.actions ?? []} />
        {(result.errors?.length ?? 0) > 0 && <PartialNote errors={result.errors ?? []} />}
      </div>
    </div>
  );
}

function previousAssessment(all: RiskAssessment[] | undefined, before: string): RiskAssessment | undefined {
  const t = new Date(before).getTime();
  return (all ?? [])
    .filter((a) => new Date(a.assessed_at).getTime() < t)
    .sort((a, b) => new Date(b.assessed_at).getTime() - new Date(a.assessed_at).getTime())[0];
}

/* ---- status --------------------------------------------------------------------------- */

function StatusCard({ result, previous }: { result: DayResult; previous?: RiskAssessment }) {
  const { registry } = useRegistry();
  const assessment = result.assessment!;
  const level = assessment.level ?? "green";
  const copy = levelCopy(level);
  const bands = levelBands(registry.alert_levels);
  const change = previous ? signedNumber(Math.round(assessment.score) - Math.round(previous.score)).replace(/^\+0$/, "±0") : null;
  const position = Math.min(100, Math.max(0, assessment.score));

  return (
    <Frame className="status" aria-labelledby="status-heading">
      <p className="kicker">Today's status</p>
      <div className="status__main">
        <div className="status__level" key={level}>
          <LevelIcon level={level} size={40} />
          <div>
            <h2 id="status-heading" className="status__word" style={{ color: levelInk(level) }}>
              {copy.word}
            </h2>
            <p className="status__meaning">{copy.meaning}</p>
          </div>
        </div>
        <div className="status__score">
          <span className="figure status__figure">{formatNumber(assessment.score, 0)}</span>
          <span className="secondary">
            of 100{change ? ` · ${change} vs yesterday` : ""}
          </span>
        </div>
      </div>

      <div className="meter" aria-hidden="true">
        <div className="meter__track">
          {bands.map((b) => (
            <span
              key={b.level}
              className="meter__band"
              style={{ flexGrow: b.to - b.from, background: b.level === level ? levelColor(b.level) : undefined }}
            />
          ))}
        </div>
        <span className="meter__marker" style={{ left: `${position}%` }} />
        <div className="meter__labels">
          {bands.map((b) => (
            <span key={b.level} style={{ flexGrow: b.to - b.from }}>
              {b.from}
            </span>
          ))}
        </div>
      </div>

      <details className="disclosure disclosure--quiet">
        <summary>Show details</summary>
        <dl className="status__facts">
          <div>
            <dt>Mission day</dt>
            <dd className="data">{result.mission_day}</dd>
          </div>
          <div>
            <dt>Assessed</dt>
            <dd className="data">{formatClock(assessment.assessed_at)}</dd>
          </div>
          {assessment.model_version && (
            <div>
              <dt>Model</dt>
              <dd>{assessment.model_version}</dd>
            </div>
          )}
        </dl>
      </details>
    </Frame>
  );
}

/* ---- contributors ----------------------------------------------------------------------- */

function Contributors({
  contributors,
  anomalies,
  score,
}: {
  contributors: readonly Contributor[];
  anomalies: readonly Anomaly[];
  score: number;
}) {
  const { spec, registry } = useRegistry();
  const total = contributors.reduce((sum, c) => sum + c.points, 0);
  const maxPoints = Math.max(...contributors.map((c) => c.points), 1);
  const bySignal = new Map(anomalies.map((a) => [a.signal, a]));

  return (
    <section className="contributors" aria-labelledby="why-heading">
      <h2 id="why-heading" className="section-label">
        Why
      </h2>
      {contributors.length === 0 ? (
        <p className="card empty-card secondary">Nothing raised your score today.</p>
      ) : (
        <ul className="group">
          {contributors.map((c, i) => {
            const s = spec(c.signal);
            const anomaly = c.signal ? bySignal.get(c.signal) : undefined;
            const without = Math.max(0, Math.min(100, total - c.points));
            const withoutLevel = levelForScore(without, registry.alert_levels);
            const valueLine =
              anomaly && s
                ? `${formatValue(anomaly.value, s)} · ${withUnit(signedNumber(anomaly.value - anomaly.baseline_center), s)} vs normal ${formatNumber(anomaly.baseline_center)}`
                : s && (s.category === "symptom" || s.category === "wellbeing")
                  ? "Reported in your check-in"
                  : s && s.category === "lab"
                    ? "Onboard lab result"
                    : c.event_id
                      ? "Stress event"
                      : "";
            return (
              <li key={`${c.label}-${i}`} className="contrib">
                <div className="contrib__top">
                  <span className="contrib__label">{c.label}</span>
                  <span className="contrib__pts data">+{formatNumber(c.points, 1)} pts</span>
                </div>
                <div className="bar" aria-hidden="true">
                  <span style={{ width: `${(c.points / maxPoints) * 100}%` }} />
                </div>
                <details className="disclosure disclosure--quiet contrib__details">
                  <summary>Show details</summary>
                  {anomaly && s && (
                    <NormalBand value={anomaly.value} center={anomaly.baseline_center} spread={anomaly.baseline_spread} spec={s} />
                  )}
                  {valueLine && <span className="caption data">{valueLine}</span>}
                  <div className="contrib__without caption">
                    <span>
                      Without it: <span className="data">{formatNumber(without, 0)}</span>
                    </span>
                    <LevelTag level={withoutLevel} />
                    <span className="visually-hidden">(score now {formatNumber(score, 0)})</span>
                  </div>
                </details>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/* ---- actions ------------------------------------------------------------------------------ */

export function ActionsPanel({ cards, heading = "What to do now" }: { cards: readonly ActionCard[]; heading?: string }) {
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const tell = [...new Set(cards.map((c) => c.escalate_to ?? "self").filter((t) => t !== "self"))];
  const totalSteps = cards.reduce((n, c) => n + (c.steps?.length ?? 0), 0);

  return (
    <section className="actions" aria-labelledby="actions-heading">
      <div className="section-head">
        <h2 id="actions-heading" className="section-label">
          {heading}
        </h2>
        {totalSteps > 0 && (
          <span className="secondary data" aria-live="polite">
            {done.size} of {totalSteps} done
          </span>
        )}
      </div>
      {totalSteps > 0 && (
        <div className="bar bar--accent" aria-hidden="true">
          <span style={{ width: `${(done.size / totalSteps) * 100}%` }} />
        </div>
      )}
      {tell.length > 0 && (
        <p className="tell">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="8" r="3.5" />
            <path d="M5 20a7 7 0 0 1 14 0" />
          </svg>
          <span>
            Tell the <strong>{tell.map((t) => humanize(t).toLowerCase()).join(" and the ")}</strong> today.
          </span>
        </p>
      )}
      {cards.length === 0 && <p className="card empty-card secondary">No action cards for this result.</p>}
      {cards.map((card) => (
        <Frame as="article" key={card.card_id} className="action-card">
          <header className="action-card__head">
            <h3 className="headline">{card.title}</h3>
            <LevelTag level={card.level} />
          </header>
          <ol className="steps">
            {(card.steps ?? []).map((step, i) => {
              const key = `${card.card_id}:${i}`;
              return (
                <li key={key}>
                  <label className="step">
                    <input type="checkbox" checked={done.has(key)} onChange={() => toggle(key)} />
                    <span>{step}</span>
                  </label>
                </li>
              );
            })}
          </ol>
          <p className="caption">
            {(card.escalate_to ?? "self") === "self" ? "Handle this yourself" : `Escalates to ${humanize(card.escalate_to!).toLowerCase()}`}
          </p>
          {card.rationale && (
            <details className="disclosure disclosure--quiet">
              <summary>Why this</summary>
              <p className="action-card__why secondary">{card.rationale}</p>
            </details>
          )}
        </Frame>
      ))}
    </section>
  );
}
