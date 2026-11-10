const solve = n => {
  if (n <= 0) return 0;
  const m = Math.floor(n / 2);
  return (m + 1) * (n - m);
};
