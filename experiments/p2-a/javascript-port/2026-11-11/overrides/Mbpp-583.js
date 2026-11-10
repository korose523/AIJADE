const solve = n => {
  let value = 1;
  for (let i = 0; i < n; i++) value = value * (4 * i + 2) / (i + 2);
  return value;
};
