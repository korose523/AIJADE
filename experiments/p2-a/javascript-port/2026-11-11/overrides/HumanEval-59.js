const solve = n => {
  if (n <= 1) return null;
  let rest = n;
  let largest = 1;
  for (let divisor = 2; divisor * divisor <= rest; divisor += divisor === 2 ? 1 : 2) {
    while (rest % divisor === 0) {
      largest = divisor;
      rest /= divisor;
    }
  }
  // The release excludes prime input from the statement and returns 1 on those inputs.
  return rest === n ? 1 : Math.max(rest, largest);
};
