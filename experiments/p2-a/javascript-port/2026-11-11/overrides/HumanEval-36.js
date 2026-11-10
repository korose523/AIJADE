// Digit DP counts sevens in multiples of each divisor, with inclusion-exclusion.
const solve = n => {
  if (n <= 0) return 0;
  const digits = String(n - 1).split('').map(Number);
  function count(divisor) {
    const memo = new Map();
    function suffix(position, remainder, tight) {
      if (position === digits.length) return [remainder === 0 ? 1 : 0, 0];
      const key = position * divisor + remainder;
      if (!tight && memo.has(key)) return memo.get(key);
      const limit = tight ? digits[position] : 9;
      let ways = 0;
      let sevens = 0;
      for (let digit = 0; digit <= limit; digit++) {
        const [nextWays, nextSevens] = suffix(position + 1, (remainder * 10 + digit) % divisor, tight && digit === limit);
        ways += nextWays;
        sevens += nextSevens + (digit === 7 ? nextWays : 0);
      }
      const result = [ways, sevens];
      if (!tight) memo.set(key, result);
      return result;
    }
    return suffix(0, 0, true)[1];
  }
  return count(11) + count(13) - count(143);
};
