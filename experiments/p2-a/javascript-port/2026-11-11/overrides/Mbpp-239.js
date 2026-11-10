const solve = (max, length) => {
  const m = Number(max);
  const n = Number(length);
  if (n === 0 || m === 0 || 2 ** (n - 1) > m) return 0;
  let prior = new Array(m + 1);
  for (let i = 0; i <= m; i++) prior[i] = i;
  for (let size = 2; size <= n; size++) {
    const next = new Array(m + 1).fill(0);
    for (let i = size; i <= m; i++) next[i] = next[i - 1] + prior[Math.floor(i / 2)];
    prior = next;
  }
  return prior[m];
};
