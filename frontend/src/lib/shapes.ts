/**
 * Level shapes as SVG paths centred on (x, y), so a mark reads without
 * colour: green circle, yellow diamond, orange triangle, red square.
 */
export function shapePath(level: string, x: number, y: number, r: number): string {
  if (level === "yellow") return `M${x} ${y - r * 1.25}L${x + r * 1.25} ${y}L${x} ${y + r * 1.25}L${x - r * 1.25} ${y}Z`;
  if (level === "orange") return `M${x} ${y - r * 1.2}L${x + r * 1.2} ${y + r * 0.9}L${x - r * 1.2} ${y + r * 0.9}Z`;
  if (level === "red") return `M${x - r} ${y - r}h${2 * r}v${2 * r}h${-2 * r}Z`;
  return `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
}
