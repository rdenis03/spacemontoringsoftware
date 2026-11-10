import { useState } from "react";
import type { ActionCard, Anomaly, Contributor, DayResult } from "../../api/types";
import { LevelIcon } from "../../components/LevelIcon";
import { LevelTag } from "../../components/LevelTag";
import { NormalBand } from "../../components/NormalBand";
import { LoadError, Loading, PartialNote } from "../../components/StateMessage";
import { formatMissionTime, formatNumber, humanize, signedNumber, withUnit } from "../../lib/format";
import { levelColor, levelCopy, levelForScore } from "../../lib/levels";
import type { AsyncState } from "../../lib/useAsync";
import { useRegistry } from "../../state/registry-context";

export default function Today({ status }: { status: AsyncState<DayResult> }) {
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

  return (
    <div className="today">
      <StatusTile result={result} />
      <ActionsPanel key={`${result.astronaut_id}-${result.as_of}`} cards={result.actions ?? []} />
      <WhyPanel contributors={assessment.contributors ?? []} anomalies={result.anomalies ?? []} score={assessment.score} />
      {(result.errors?.length ?? 0) > 0 && (
        <div className="today__note">
          <PartialNote errors={result.errors ?? []} />
        </div>
      )}
    </div>
  );
}

function StatusTile({ result }: { result: DayResult }) {
  const assessment = result.assessment!;
  const level = assessment.level ?? "green";
  const copy = levelCopy(level);
  return (
    <section
      className="status-tile card"
      style={{ ["--tile-level" as string]: levelColor(level) }}
      aria-labelledby="status-heading"
    >
      {/* key: the tile fades in again when the level changes */}
      <div key={level} className="status-tile__level">
        <LevelIcon level={level} size={44} />
        <div>
          <h2 id="status-heading" className="status-tile__word">
            {copy.word}
          </h2>
          <p className="status-tile__meaning">{copy.meaning}</p>
        </div>
      </div>
      <dl className="status-tile__facts">
        <div>
          <dt>Score</dt>
          <dd>
            <span className="data">{formatNumber(assessment.score, 0)}</span> of 100
          </dd>
        </div>
        <div>
          <dt>Mission day</dt>
          <dd className="data">{result.mission_day}</dd>
        </div>
        <div>
          <dt>Assessed</dt>
          <dd className="data">{formatMissionTime(assessment.assessed_at)}</dd>
        </div>
      </dl>
      {assessment.model_version && <p className="status-tile__model">Scored by {assessment.model_version}</p>}
    </section>
  );
}

function WhyPanel({
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
    <section className="why card" aria-labelledby="why-heading">
      <h2 id="why-heading" className="section-label">
        Why
      </h2>
      {contributors.length === 0 ? (
        <p className="secondary">Nothing raised your score today.</p>
      ) : (
        <ul className="why__list">
          {contributors.map((c, i) => {
            const s = spec(c.signal);
            const anomaly = c.signal ? bySignal.get(c.signal) : undefined;
            const without = Math.min(100, total - c.points);
            const withoutLevel = levelForScore(without, registry.alert_levels);
            const clearsWord = s && (s.category === "symptom" || s.category === "wellbeing") ? "clears" : "returns to your normal";
            return (
              <li key={`${c.label}-${i}`} className="why__item">
                <div className="why__head">
                  <span>{c.label}</span>
                  <span className="data why__points">
                    {formatNumber(c.points, 1)} pts
                  </span>
                </div>
                <div className="why__bar" aria-hidden="true">
                  <span style={{ width: `${(c.points / maxPoints) * 100}%` }} />
                </div>
                {anomaly && s && (
                  <div className="why__band">
                    <NormalBand
                      value={anomaly.value}
                      center={anomaly.baseline_center}
                      spread={anomaly.baseline_spread}
                      spec={s}
                    />
                    <span className="secondary data">
                      {withUnit(signedNumber(anomaly.value - anomaly.baseline_center), s)} vs normal
                    </span>
                  </div>
                )}
                {c.signal && (
                  <p className="why__whatif secondary">
                    If this {clearsWord}: <span className="data">{formatNumber(score, 0)}</span> →{" "}
                    <span className="data">{formatNumber(without, 0)}</span> <LevelTag level={withoutLevel} />
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ActionsPanel({ cards }: { cards: readonly ActionCard[] }) {
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const tell = [...new Set(cards.map((c) => c.escalate_to ?? "self").filter((t) => t !== "self"))];

  return (
    <section className="actions" aria-labelledby="actions-heading">
      <h2 id="actions-heading" className="section-label">
        What to do now
      </h2>
      {tell.length > 0 && (
        <p className="actions__tell">
          <strong>Tell:</strong> {tell.map((t) => humanize(t)).join(", ")}
        </p>
      )}
      {cards.length === 0 && <p className="secondary card">No action cards for this result.</p>}
      {cards.map((card) => (
        <article key={card.card_id} className="action-card card">
          <header className="action-card__head">
            <h3>{card.title}</h3>
            <LevelTag level={card.level} />
          </header>
          <ol className="action-card__steps">
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
          <p className="secondary">{card.rationale}</p>
          <p className="action-card__who secondary">
            Who to tell: {(card.escalate_to ?? "self") === "self" ? "no one else needed" : humanize(card.escalate_to!)}
          </p>
        </article>
      ))}
    </section>
  );
}
