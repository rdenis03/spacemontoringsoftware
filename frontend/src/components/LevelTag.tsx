import { levelCopy, levelInk } from "../lib/levels";
import { LevelIcon } from "./LevelIcon";
import "./LevelTag.css";

/** Inline level: shape mark + word in the level's text colour. Never colour alone. */
export function LevelTag({ level, label }: { level: string; label?: string }) {
  return (
    <span className="level-tag" style={{ color: levelInk(level) }}>
      <LevelIcon level={level} size={10} />
      {label ?? levelCopy(level).word}
    </span>
  );
}
