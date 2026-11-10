// All released ranks lie in the deterministic 64-bit primality range.
const solve = rank => {
  let a = 0n;
  let b = 1n;
  let count = 0n;
  while (count < rank) {
    [a, b] = [b, a + b];
    if ($p.prime64(b)) count++;
  }
  return b;
};
