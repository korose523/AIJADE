const solve = value => {
  const n = Number(value);
  for (let divisor = 2; divisor * divisor <= n; divisor += divisor === 2 ? 1 : 2) {
    if (n % divisor === 0) return n / divisor;
  }
  return 1;
};
