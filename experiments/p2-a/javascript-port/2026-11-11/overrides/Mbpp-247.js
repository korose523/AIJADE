const solve = text => {
  const chars = $p.iter(text);
  const n = chars.length;
  const lengths = new Uint32Array(n);
  for (let left = n - 1; left >= 0; left--) {
    let diagonal = 0;
    lengths[left] = 1;
    for (let right = left + 1; right < n; right++) {
      const prior = lengths[right];
      lengths[right] = chars[left] === chars[right] ? diagonal + 2 : Math.max(prior, lengths[right - 1]);
      diagonal = prior;
    }
  }
  return lengths[n - 1];
};
