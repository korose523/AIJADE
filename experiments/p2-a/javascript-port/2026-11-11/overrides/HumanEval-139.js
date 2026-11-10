// Cache exact prefix products of the factorials already computed in this task process.
let factorial = 1n;
const products = [1n, 1n];
const solve = value => {
  const n = Math.max(0, Number(value));
  for (let i = products.length; i <= n; i++) {
    factorial *= BigInt(i);
    products.push(products[i - 1] * factorial);
  }
  return products[n];
};
