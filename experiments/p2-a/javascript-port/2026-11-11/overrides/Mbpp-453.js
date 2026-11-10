const solve = n => {
  if (n <= 0 || n % 2 !== 0) return 0;
  const half = n / 2;
  let total = 0;
  for (let d = 1; d * d <= half; d++) {
    if (half % d === 0) total += d + (d * d === half ? 0 : half / d);
  }
  return total * 2;
};
