const solve = n => {
  const target = 10n ** (n - 1n);
  let lower = 0n;
  let upper = 1n;
  const triangular = k => k * (k + 1n) / 2n;
  while (triangular(upper) < target) upper *= 2n;
  while (upper - lower > 1n) {
    const middle = (lower + upper) / 2n;
    if (triangular(middle) < target) lower = middle;
    else upper = middle;
  }
  return upper;
};
