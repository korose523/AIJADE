const solve = n => {
  const memo = new Map([[0, 0]]);
  function best(value) {
    if (memo.has(value)) return memo.get(value);
    const result = Math.max(value, best(Math.floor(value / 2)) + best(Math.floor(value / 3))
      + best(Math.floor(value / 4)) + best(Math.floor(value / 5)));
    memo.set(value, result);
    return result;
  }
  return best(Number(n));
};
