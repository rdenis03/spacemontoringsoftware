import { levelColor, levelCopy } from "../lib/levels";
import { LevelIcon } from "./LevelIcon";
import "./LevelTag.css";

/** Small inline level: icon + word, coloured. Never colour alone. */
export function LevelTag({ level }: { level: string }) {
  return (
    <span className="level-tag" style={{ color: levelColor(level) }}>
      <LevelIcon level={level} size={14} />
      {levelCopy(level).word}
    </span>
  );
}
