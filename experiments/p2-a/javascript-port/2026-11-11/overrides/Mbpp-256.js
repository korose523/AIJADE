const solve = value => {
  const n = Number(value);
  const marked = new Uint8Array(n);
  let count = 0;
  for (let p = 2; p < n; p++) {
    if (marked[p]) continue;
    count++;
    for (let multiple = p * p; multiple < n; multiple += p) marked[multiple] = 1;
  }
  return count;
};
