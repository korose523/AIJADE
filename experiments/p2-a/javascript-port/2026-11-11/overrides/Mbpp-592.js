// Vandermonde's identity reduces the adjacent coefficient products to one coefficient.
const solve = value => {
  const n = BigInt(value);
  let coefficient = 1n;
  for (let k = 1n; k <= n - 1n; k++) coefficient = coefficient * (2n * n + 1n - k) / k;
  return coefficient;
};
