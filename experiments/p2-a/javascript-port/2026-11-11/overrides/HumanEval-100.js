const solve = value => {
  const n = Number(value);
  const pile = new Array(n);
  for (let i = 0; i < n; i++) pile[i] = n + 2 * i;
  return pile;
};
