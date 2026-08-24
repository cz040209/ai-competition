import { useMemo } from "react";

const COUNT = 14;

export function Motes() {
  const motes = useMemo(
    () =>
      Array.from({ length: COUNT }, (_, i) => ({
        left: `${(i * 37) % 100}%`,
        top: `${(i * 61) % 100}%`,
        size: 3 + (i % 5) * 2,
        duration: 14 + (i % 7) * 3,
        delay: -(i * 1.7),
      })),
    [],
  );

  return (
    <div className="motes" aria-hidden="true">
      {motes.map((mote, i) => (
        <i
          key={i}
          className="mote"
          style={{
            left: mote.left,
            top: mote.top,
            width: mote.size,
            height: mote.size,
            animation: `drift ${mote.duration}s linear ${mote.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}
