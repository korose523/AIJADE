const solve = (left, right) => {
  const width = Math.min(left[1], right[1]) - Math.max(left[0], right[0]);
  return $p.prime64(width) ? 'YES' : 'NO';
};
