/** Format the integer-sen amount received from the API for display only. */
export function fmt(sen: number): string {
  return (sen / 100).toLocaleString("en-MY", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
