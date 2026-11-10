const solve = text => {
  const parts = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text.trim());
  if (!parts || !(parts[2] || parts[3])) throw new Error('finite decimal text required');
  const fraction = parts[3] ?? '';
  const magnitude = BigInt(parts[2] + fraction);
  const scale = BigInt(fraction.length) - BigInt(parts[4] ?? 0);
  let rounded;
  if (scale <= 0n) rounded = magnitude * 10n ** (-scale);
  else {
    const denominator = 10n ** scale;
    rounded = magnitude / denominator;
    if (2n * (magnitude % denominator) >= denominator) rounded++;
  }
  return parts[1] === '-' ? -rounded : rounded;
};
