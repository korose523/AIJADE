const solve = limit => {
  if (limit < 2) return 0;
  const sums = new Uint32Array(limit + 1);
  sums.fill(1);
  for (let divisor = 2; divisor * 2 <= limit; divisor++) {
    for (let multiple = divisor * 2; multiple <= limit; multiple += divisor) sums[multiple] += divisor;
  }
  function divisorSum(n) {
    if (n <= limit) return sums[n];
    let sum = 1;
    for (let d = 2; d * d <= n; d++) {
      if (n % d === 0) sum += d + (d * d === n ? 0 : n / d);
    }
    return sum;
  }
  let sum = 0;
  for (let n = 2; n <= limit; n++) {
    const partner = sums[n];
    if (partner !== n && divisorSum(partner) === n) sum += n;
  }
  return sum;
};
