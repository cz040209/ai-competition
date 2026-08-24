type PlaceholderProps = { title: string; blurb: string; week: string };

export function Placeholder({ title, blurb, week }: PlaceholderProps) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>{title}</p>
          <h1>{title}</h1>
        </div>
      </div>
      <div className="pad">
        <section className="card">
          <p className="voice" style={{ margin: 0, fontSize: 16, lineHeight: 1.45 }}>{blurb}</p>
          <p style={{ margin: "12px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
            Coming in week {week}.
          </p>
        </section>
      </div>
    </>
  );
}
