const solve = value => {
  const n = Number(value);
  if (n === 1 || n === 2) return 1;
  const seq = new Uint32Array(n + 1);
  seq[1] = seq[2] = 1;
  for (let i = 3; i <= n; i++) {
    const previous = seq[i - 1];
    seq[i] = seq[previous] + seq[i - previous];
  }
  return seq[n];
};
