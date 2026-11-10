const solve = value => {
  const n = BigInt(value);
  if (n <= 0n) return 0n;
  return 8n * n * n * (n + 1n) ** 2n * (2n * n * n + 2n * n - 1n) / 3n;
};
