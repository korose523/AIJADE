// Exact decimal representation of the inclusion-exclusion count.
const solve = value => {
  const n = Number(value);
  return n === 1 ? '1' : '18' + '0'.repeat(n - 2);
};
