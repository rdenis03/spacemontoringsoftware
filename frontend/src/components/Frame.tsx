import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * A rounded card: the one container in the ORBIT design (DESIGN.md › Shape).
 * `as` picks the element (section, li, fieldset, aside…) so semantics stay.
 */
export function Frame({
  as: Tag = "section",
  className = "",
  style,
  children,
  ...rest
}: {
  as?: ElementType;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
  [attr: string]: unknown;
}) {
  return (
    <Tag className={`card ${className}`.trim()} style={style} {...rest}>
      {children}
    </Tag>
  );
}

