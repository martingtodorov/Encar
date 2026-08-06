/**
 * Where the results list was left, handed from the car page back to the list.
 *
 * A module variable rather than navigation state, because the way back is a real history POP:
 * the entry we land on was written before the visitor scrolled, so it carries nothing we could
 * read. One-shot - taking it clears it, so a later reload does not jump.
 */
let offset = null;

export const setBackScroll = (y) => {
  offset = y;
};

export const takeBackScroll = () => {
  const y = offset;
  offset = null;
  return y;
};
