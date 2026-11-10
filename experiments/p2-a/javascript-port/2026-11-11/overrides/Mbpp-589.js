const solve = (a, b) => {
  const low = Math.max(0, Math.min(a, b));
  const high = Math.max(a, b);
  const squares = [];
  for (let root = Math.ceil(Math.sqrt(low)); root * root <= high; root++) squares.push(root * root);
  return squares;
};
