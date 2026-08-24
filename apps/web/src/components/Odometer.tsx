import { useEffect, useState } from "react";

import { fmt } from "../lib/money";

type OdometerProps = { sen: number; size?: number; rm?: boolean };

export function Odometer({ sen, size = 52, rm = true }: OdometerProps) {
  const text = fmt(sen);
  const [shown, setShown] = useState(text);

  useEffect(() => {
    setShown(text);
  }, [text]);

  return (
    <div className="odo" style={{ fontSize: size }} aria-label={`RM${text}`}>
      {rm && <span className="odo-rm">RM</span>}
      {shown.split("").map((character, index) => (
        <span
          key={`${index}-${character}`}
          className={`odo-d ${character === "," || character === "." ? "odo-sep" : ""}`}
          style={{ animationDelay: `${index * 45}ms` }}
        >
          {character}
        </span>
      ))}
    </div>
  );
}
