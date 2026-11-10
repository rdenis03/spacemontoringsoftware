import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * Blueprint frame: a hairline box with registration marks at the corners,
 * the signature object of the ORBIT Instrument design.
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
    <Tag className={`blueprint ${className}`.trim()} style={style} {...rest}>
      <Corners />
      {children}
    </Tag>
  );
}

export function Corners() {
  return (
    <>
      <i className="corner tl" aria-hidden="true" />
      <i className="corner tr" aria-hidden="true" />
      <i className="corner bl" aria-hidden="true" />
      <i className="corner br" aria-hidden="true" />
    </>
  );
}
