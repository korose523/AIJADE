const solve = (start, end) => {
  const values = [];
  for (let n = Math.max(1, Number(start)); n <= end; n++) {
    let value = n;
    while (value > 0) {
      const digit = value % 10;
      if (digit === 0 || n % digit !== 0) break;
      value = Math.floor(value / 10);
    }
    if (value === 0) values.push(n);
  }
  return values;
};
