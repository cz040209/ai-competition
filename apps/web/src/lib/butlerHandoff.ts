/**
 * One question, handed from a screen that cannot answer it to the one that can.
 *
 * The Plan screen's ask box turns a sentence into filters, which is the right
 * answer for "halal, under RM15, not far to walk" and no answer at all for
 * "what should I actually eat tonight". The part that produced no filter comes
 * back from the server as `unread`, and the offer made there is to take the
 * whole sentence to the Butler, which can reason about it and can commit a
 * plan through the approval card. This is where the sentence waits in between.
 *
 * A module slot rather than React state or a context, because the two screens
 * are never mounted at the same time: one tab is on screen and the others do
 * not exist, so there is nothing below the app shell for both of them to read.
 * Surviving that unmount is the whole job.
 *
 * Taken once, and emptied by the taking. A question left behind would be asked
 * again every time the Butler is opened, and the user would be reading an
 * answer to a sentence they typed hours ago.
 */
let pending: string | null = null;

/** Leave a question for the Butler to ask when it next opens. */
export function handToButler(question: string): void {
  const trimmed = question.trim();
  pending = trimmed === "" ? null : trimmed;
}

/** The waiting question, if there is one, and the slot is empty afterwards. */
export function takeButlerHandoff(): string | null {
  const question = pending;
  pending = null;
  return question;
}
